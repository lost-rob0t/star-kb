from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .llm_rate import LocalLeaseLimiter, QuotaClient, RateLimitError, SubscriptionLimiter

CONFIG_SCHEMA = "starintel.llm.config.v1"
PLAN_SCHEMA = "starintel.llm.plan.v1"
REVIEW_SCHEMA = "starintel.llm.review.v1"


class HarnessError(RuntimeError):
    def __init__(self, code: str, detail: str = "", retry_after: float = 0.0):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.retry_after = max(0.0, float(retry_after))


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    text: str
    elapsed_ms: int
    stderr: str


def config_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if value := os.environ.get("STARINTEL_LLM_CONFIG"):
        return Path(value).expanduser()
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "starintel" / "llm-harness.json"


def load_config(path: str | None = None) -> dict[str, Any]:
    filename = config_path(path)
    try:
        raw = json.loads(filename.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HarnessError("config_unavailable", str(filename)) from exc
    except ValueError as exc:
        raise HarnessError("config_invalid_json", str(filename)) from exc

    if not isinstance(raw, dict) or raw.get("schema") != CONFIG_SCHEMA:
        raise HarnessError("config_invalid_schema", str(filename))
    for section in ("proxy", "providers", "profiles", "rate_limits"):
        if not isinstance(raw.get(section), dict):
            raise HarnessError("config_missing_section", section)
    return raw


def _bounded(value: str, limit: int) -> str:
    raw = value.encode("utf-8", "replace")
    if len(raw) <= limit:
        return value
    return raw[:limit].decode("utf-8", "ignore")


def _json_values(text: str) -> list[Any]:
    values: list[Any] = []
    stripped = text.strip()
    if stripped:
        try:
            values.append(json.loads(stripped))
        except ValueError:
            pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(json.loads(line))
        except ValueError:
            continue
    return values


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_strings(item))
        return result
    if isinstance(value, dict):
        result = []
        preferred = ("output_text", "text", "content", "message")
        for key in preferred:
            if key in value:
                result.extend(_strings(value[key]))
        for key, item in value.items():
            if key not in preferred and isinstance(item, (dict, list)):
                result.extend(_strings(item))
        return result
    return []


def provider_text(parser: str, stdout: str) -> str:
    if parser == "text":
        return stdout.strip()
    values = _json_values(stdout)
    if parser == "json":
        if len(values) != 1:
            raise HarnessError("provider_json_invalid")
        return json.dumps(values[0], ensure_ascii=False)
    if parser == "codex_jsonl":
        found: list[str] = []
        for value in values:
            found.extend(_strings(value))
        found = [item.strip() for item in found if item.strip()]
        if not found:
            raise HarnessError("codex_output_missing_text")
        return found[-1]
    raise HarnessError("provider_parser_unknown", parser)


def typed_json(text: str, schema: str) -> dict[str, Any]:
    for value in reversed(_json_values(text)):
        if isinstance(value, dict) and value.get("schema") == schema:
            return value

    decoder = json.JSONDecoder()
    starts = [index for index, char in enumerate(text) if char == "{"]
    for start in reversed(starts):
        try:
            value, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("schema") == schema:
            return value
    raise HarnessError("typed_json_missing", schema)


class PrologVerifier:
    def __init__(self, path: Path, swipl: str = "swipl", timeout: float = 15):
        self.path = path
        self.swipl = swipl
        self.timeout = timeout

    def verify(self, plan: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory(prefix="starintel-plan-") as directory:
            filename = Path(directory) / "plan.json"
            filename.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            goal = f"star_llm_harness:validate_plan_file('{filename.as_posix()}')"
            try:
                result = subprocess.run(
                    [self.swipl, "-q", "-s", str(self.path), "-g", goal, "-t", "halt"],
                    text=True,
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
            except OSError as exc:
                raise HarnessError("prolog_verifier_unavailable", str(exc)) from exc
            except subprocess.TimeoutExpired as exc:
                raise HarnessError("prolog_verifier_timeout") from exc
            if result.returncode:
                detail = (result.stderr or result.stdout or "plan rejected").strip()
                raise HarnessError("plan_rejected", detail[-4000:])


class StarIntelLLMHarness:
    def __init__(self, config: dict[str, Any], repo_root: Path | None = None):
        self.config = config
        proxy = config["proxy"]
        quota_url = str(proxy.get("quota_base_url") or proxy.get("base_url") or "")
        self.subscription = SubscriptionLimiter(
            QuotaClient(quota_url, float(proxy.get("timeout_seconds", 3))),
            config["rate_limits"],
        )

        rate_file = config.get("rate_state_file")
        if rate_file:
            state_path = Path(str(rate_file)).expanduser()
        else:
            runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
            state_path = runtime / f"starintel-llm-rate-{os.getuid()}.json"
        self.local = LocalLeaseLimiter(state_path)

        root = repo_root or Path(__file__).resolve().parents[1]
        verifier = config.get("prolog_verifier")
        verifier_path = Path(str(verifier)).expanduser() if verifier else root / "kb" / "core" / "star_llm_harness.pl"
        self.verifier = PrologVerifier(verifier_path, str(config.get("swipl", "swipl")))

    def profile(self, name: str) -> dict[str, Any]:
        value = self.config["profiles"].get(name)
        if not isinstance(value, dict):
            raise HarnessError("profile_missing", name)
        return value

    def provider(self, name: str) -> dict[str, Any]:
        value = self.config["providers"].get(name)
        if not isinstance(value, dict):
            raise HarnessError("provider_missing", name)
        return value

    def check_rate(self, provider_name: str):
        provider = self.provider(provider_name)
        quota_provider = provider.get("quota_provider")
        if not isinstance(quota_provider, str):
            raise HarnessError("provider_quota_missing", provider_name)
        return self.subscription.check(quota_provider)

    def call(self, provider_name: str, prompt: str, wait_seconds: float = 0) -> ProviderResult:
        provider = self.provider(provider_name)
        quota_provider = provider.get("quota_provider")
        if not isinstance(quota_provider, str):
            raise HarnessError("provider_quota_missing", provider_name)

        decision = self.subscription.check(quota_provider)
        if not decision.allowed:
            raise HarnessError(
                "subscription_rate_limited",
                f"{quota_provider}: {decision.reason}",
                decision.retry_after,
            )

        policy = self.config["rate_limits"][quota_provider]
        try:
            token = self.local.acquire(
                quota_provider,
                max_concurrency=int(policy.get("max_concurrency", 1)),
                min_interval_seconds=float(policy.get("min_interval_seconds", 0)),
                lease_seconds=float(policy.get("lease_seconds", 1800)),
                wait_seconds=wait_seconds,
            )
        except RateLimitError as exc:
            raise HarnessError(exc.code, exc.detail, exc.retry_after) from exc

        try:
            decision = self.subscription.check(quota_provider)
            if not decision.allowed:
                raise HarnessError(
                    "subscription_rate_limited",
                    f"{quota_provider}: {decision.reason}",
                    decision.retry_after,
                )
            return self._run_provider(provider_name, provider, prompt)
        finally:
            self.local.release(quota_provider, token)

    def _run_provider(
        self,
        provider_name: str,
        provider: dict[str, Any],
        prompt: str,
    ) -> ProviderResult:
        argv = provider.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise HarnessError("provider_argv_invalid", provider_name)

        actual = list(argv)
        if provider.get("append_prompt", False):
            actual.append(prompt)
        stdin = prompt if provider.get("stdin_prompt", True) else None
        timeout = float(provider.get("timeout_seconds", 900))
        max_output = int(provider.get("max_output_bytes", 2_000_000))

        started = time.monotonic()
        try:
            result = subprocess.run(
                actual,
                input=stdin,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except OSError as exc:
            raise HarnessError("provider_unavailable", f"{provider_name}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise HarnessError("provider_timeout", provider_name) from exc

        elapsed = int((time.monotonic() - started) * 1000)
        stdout = _bounded(result.stdout or "", max_output)
        stderr = _bounded(result.stderr or "", max_output)
        if result.returncode:
            raise HarnessError(
                "provider_failed",
                f"{provider_name}: exit {result.returncode}: {stderr[-4000:]}",
            )

        text = provider_text(str(provider.get("parser", "text")), stdout)
        if not text:
            raise HarnessError("provider_empty_output", provider_name)
        return ProviderResult(provider_name, text, elapsed, stderr)

    def plan(self, goal: str, profile_name: str = "main", wait_seconds: float = 0) -> dict[str, Any]:
        profile = self.profile(profile_name)
        planner = profile.get("planner")
        allowed = profile.get("allowed_providers")
        if not isinstance(planner, str):
            raise HarnessError("profile_planner_missing", profile_name)
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise HarnessError("profile_allowed_providers_invalid", profile_name)

        prompt = (
            "You are StarIntel's planning worker. Return exactly one JSON object and no prose. "
            f'Use schema "{PLAN_SCHEMA}". '
            "Every step must contain id, kind='model', provider, prompt, depends_on. "
            "The graph must be acyclic and providers must come from this allowlist: "
            f"{json.dumps(allowed)}. Goal: {goal}"
        )
        result = self.call(planner, prompt, wait_seconds)
        plan = typed_json(result.text, PLAN_SCHEMA)
        if plan.get("goal") != goal:
            raise HarnessError("plan_goal_mismatch")

        steps = plan.get("steps")
        if not isinstance(steps, list):
            raise HarnessError("plan_steps_invalid")
        allowset = set(allowed)
        for step in steps:
            if not isinstance(step, dict) or step.get("provider") not in allowset:
                raise HarnessError("plan_provider_not_allowed")

        self.verifier.verify(plan)
        return plan

    def execute(
        self,
        plan: dict[str, Any],
        profile_name: str = "main",
        wait_seconds: float = 0,
    ) -> dict[str, Any]:
        self.verifier.verify(plan)
        profile = self.profile(profile_name)
        max_parallel = max(1, int(profile.get("max_parallel", 1)))
        steps = {step["id"]: step for step in plan["steps"]}
        pending = set(steps)
        results: dict[str, dict[str, Any]] = {}

        while pending:
            ready = [
                steps[step_id]
                for step_id in sorted(pending)
                if all(dep in results for dep in steps[step_id].get("depends_on", []))
            ]
            if not ready:
                raise HarnessError("plan_deadlock")

            batch = ready[:max_parallel]
            snapshot = dict(results)
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                jobs = {
                    pool.submit(self._execute_step, step, snapshot, wait_seconds): step["id"]
                    for step in batch
                }
                completed: dict[str, dict[str, Any]] = {}
                for future in as_completed(jobs):
                    step_id = jobs[future]
                    completed[step_id] = future.result()

            for step_id in sorted(completed):
                results[step_id] = completed[step_id]
                pending.remove(step_id)

        return {
            "schema": "starintel.llm.execution.v1",
            "goal": plan["goal"],
            "profile": profile_name,
            "steps": [results[step["id"]] for step in plan["steps"]],
        }

    def _execute_step(
        self,
        step: dict[str, Any],
        results: dict[str, dict[str, Any]],
        wait_seconds: float,
    ) -> dict[str, Any]:
        dependencies = {
            dep: results[dep]["text"]
            for dep in step.get("depends_on", [])
        }
        prompt = str(step["prompt"])
        if dependencies:
            prompt += "\n\nDependency results:\n" + json.dumps(dependencies, ensure_ascii=False)
        result = self.call(str(step["provider"]), prompt, wait_seconds)
        return {
            "id": step["id"],
            "provider": result.provider,
            "text": result.text,
            "elapsed_ms": result.elapsed_ms,
        }

    def reviews(
        self,
        goal: str,
        plan: dict[str, Any],
        execution: dict[str, Any],
        profile_name: str = "main",
        wait_seconds: float = 0,
    ) -> list[dict[str, Any]]:
        profile = self.profile(profile_name)
        names = profile.get("reviewers") or []
        if not isinstance(names, list):
            raise HarnessError("reviewers_invalid", profile_name)
        if not names:
            return []

        evidence = _bounded(
            json.dumps({"goal": goal, "plan": plan, "execution": execution}, ensure_ascii=False),
            int(profile.get("review_context_bytes", 200_000)),
        )

        def review(name: str) -> dict[str, Any]:
            reviewer = self.profile(name)
            provider = reviewer.get("provider")
            if not isinstance(provider, str):
                raise HarnessError("reviewer_provider_missing", name)
            prompt = (
                "Independently review this StarIntel result. Return exactly one JSON object and no prose. "
                f'Use schema "{REVIEW_SCHEMA}", verdict approve|changes|block, and nonempty summary. '
                f"Evidence:\n{evidence}"
            )
            result = self.call(provider, prompt, wait_seconds)
            payload = typed_json(result.text, REVIEW_SCHEMA)
            if payload.get("verdict") not in {"approve", "changes", "block"}:
                raise HarnessError("review_verdict_invalid", name)
            if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
                raise HarnessError("review_summary_invalid", name)
            return {"profile": name, "provider": provider, **payload}

        limit = max(1, int(profile.get("review_parallel", len(names))))
        output = []
        with ThreadPoolExecutor(max_workers=min(limit, len(names))) as pool:
            jobs = {pool.submit(review, name): name for name in names}
            for future in as_completed(jobs):
                output.append(future.result())
        return sorted(output, key=lambda item: item["profile"])

    def run(self, goal: str, profile_name: str = "main", wait_seconds: float = 0) -> dict[str, Any]:
        plan = self.plan(goal, profile_name, wait_seconds)
        execution = self.execute(plan, profile_name, wait_seconds)
        reviews = self.reviews(goal, plan, execution, profile_name, wait_seconds)

        policy = self.profile(profile_name).get("review_policy") or {}
        min_approvals = int(policy.get("min_approvals", 0))
        approvals = sum(1 for review in reviews if review["verdict"] == "approve")
        blocks = sum(1 for review in reviews if review["verdict"] == "block")
        accepted = blocks == 0 and approvals >= min_approvals

        return {
            "schema": "starintel.llm.run.v1",
            "goal": goal,
            "profile": profile_name,
            "plan": plan,
            "execution": execution,
            "reviews": reviews,
            "accepted": accepted,
        }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starintel-llm")
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profiles")

    quota = sub.add_parser("quota")
    quota.add_argument("--provider")

    rate = sub.add_parser("check-rate")
    rate.add_argument("provider")

    plan = sub.add_parser("plan")
    plan.add_argument("goal")
    plan.add_argument("--profile", default="main")
    plan.add_argument("--wait-seconds", type=float, default=0)

    run = sub.add_parser("run")
    run.add_argument("goal")
    run.add_argument("--profile", default="main")
    run.add_argument("--wait-seconds", type=float, default=0)

    args = parser.parse_args(argv)
    config = load_config(args.config)
    harness = StarIntelLLMHarness(config)

    if args.command == "profiles":
        print(json.dumps(config["profiles"], ensure_ascii=False, indent=2))
        return 0
    if args.command == "quota":
        snapshot = harness.subscription.client.snapshot()
        if args.provider:
            providers = snapshot.get("providers", [])
            snapshot = next(
                (item for item in providers if isinstance(item, dict) and item.get("id") == args.provider),
                {"state": "missing", "id": args.provider},
            )
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    if args.command == "check-rate":
        decision = harness.check_rate(args.provider)
        print(json.dumps(decision.__dict__, ensure_ascii=False, indent=2))
        return 0 if decision.allowed else 75
    if args.command == "plan":
        print(json.dumps(
            harness.plan(args.goal, args.profile, args.wait_seconds),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.command == "run":
        result = harness.run(args.goal, args.profile, args.wait_seconds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["accepted"] else 3
    return 2


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except RateLimitError as exc:
        error = HarnessError(exc.code, exc.detail, exc.retry_after)
    except HarnessError as exc:
        error = exc

    payload = {"ok": False, "error": error.code, "detail": error.detail}
    if error.retry_after:
        payload["retry_after"] = error.retry_after
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    return 75 if "rate" in error.code else 2


if __name__ == "__main__":
    raise SystemExit(main())
