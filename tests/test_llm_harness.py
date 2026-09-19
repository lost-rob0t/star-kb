from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prolog_star_kb.llm_harness import (
    HarnessError,
    PrologVerifier,
    StarIntelLLMHarness,
    provider_text,
)
from prolog_star_kb.llm_rate import LocalLeaseLimiter, RateDecision, RateLimitError, _window_decision


class QuotaHandler(BaseHTTPRequestHandler):
    payload: dict = {}

    def do_GET(self):
        if self.path != "/api/v1/quotas":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(self.payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class QuotaServer:
    def __init__(self, payload: dict):
        QuotaHandler.payload = payload
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuotaHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def quota_payload() -> dict:
    now = time.time()
    def provider(provider_id: str):
        return {
            "id": provider_id,
            "state": "ok",
            "plan": "test",
            "windows": [
                {
                    "id": f"{provider_id}:5h",
                    "state": "ok",
                    "used_percent": 0,
                    "window_seconds": 18_000,
                    "resets_at": now + 18_000,
                },
                {
                    "id": f"{provider_id}:week",
                    "state": "ok",
                    "used_percent": 0,
                    "window_seconds": 604_800,
                    "resets_at": now + 604_800,
                },
            ],
        }
    return {"schema_version": 1, "providers": [provider("gpt"), provider("zai")]}


def fake_provider(path: Path) -> None:
    path.write_text(
        """
import json
import sys

mode = sys.argv[1]
prompt = sys.stdin.read()
goal = "build thing"
if mode == "planner":
    print(json.dumps({
        "schema": "starintel.llm.plan.v1",
        "mode": "plan",
        "goal": goal,
        "steps": [
            {
                "id": "code",
                "kind": "model",
                "provider": "worker",
                "agent_profile": "worker-code",
                "prompt": "implement the bounded slice",
                "depends_on": []
            }
        ]
    }))
elif mode == "worker":
    if "SPECIALIST_MARKER" not in prompt:
        raise SystemExit(3)
    print("worker-ok")
elif mode == "review":
    print(json.dumps({
        "schema": "starintel.llm.review.v1",
        "verdict": "approve",
        "summary": "verified"
    }))
elif mode == "codex-jsonl":
    plan = json.dumps({
        "schema": "starintel.llm.plan.v1",
        "goal": goal,
        "steps": []
    })
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": plan}}))
else:
    raise SystemExit(2)
""".lstrip(),
        encoding="utf-8",
    )


class RateTests(unittest.TestCase):
    def test_pacing_blocks_usage_ahead_of_elapsed_window(self):
        now = 1000.0
        window = {
            "state": "ok",
            "used_percent": 50,
            "window_seconds": 1000,
            "resets_at": 1900,
        }
        decision = _window_decision(
            window,
            {"reserve_percent": 10, "burst_percent": 5, "unknown_policy": "deny"},
            now,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ahead_of_budget_curve")
        self.assertGreater(decision.retry_after, 0)

    def test_reserve_floor_blocks_before_provider_exhaustion(self):
        decision = _window_decision(
            {"state": "ok", "used_percent": 91},
            {"reserve_percent": 10, "burst_percent": 5},
            1000,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "reserve_floor")

    def test_minimum_launch_interval_survives_release(self):
        with tempfile.TemporaryDirectory() as directory:
            limiter = LocalLeaseLimiter(Path(directory) / "rate.json")
            token = limiter.acquire(
                "gpt",
                max_concurrency=2,
                min_interval_seconds=10,
                lease_seconds=30,
            )
            limiter.release("gpt", token)
            with self.assertRaises(RateLimitError) as error:
                limiter.acquire(
                    "gpt",
                    max_concurrency=2,
                    min_interval_seconds=10,
                    lease_seconds=30,
                )
        self.assertEqual(error.exception.code, "local_rate_limited")
        self.assertIn("interval", error.exception.detail)
        self.assertGreater(error.exception.retry_after, 0)


class ParserTests(unittest.TestCase):
    def test_codex_jsonl_extracts_agent_message(self):
        nested = json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "PLAN_OK"},
        })
        self.assertEqual(provider_text("codex_jsonl", nested), "PLAN_OK")


@unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog required")
class HarnessE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fake = self.root / "fake_provider.py"
        fake_provider(self.fake)

    def tearDown(self):
        self.temp.cleanup()

    def config(self, quota_url: str) -> dict:
        command = [sys.executable, str(self.fake)]
        return {
            "schema": "starintel.llm.config.v1",
            "proxy": {"base_url": quota_url, "timeout_seconds": 2},
            "providers": {
                "planner": {
                    "argv": command + ["planner"],
                    "stdin_prompt": True,
                    "parser": "text",
                    "quota_provider": "gpt",
                },
                "worker": {
                    "argv": command + ["worker"],
                    "stdin_prompt": True,
                    "parser": "text",
                    "quota_provider": "zai",
                },
                "review-gpt-provider": {
                    "argv": command + ["review"],
                    "stdin_prompt": True,
                    "parser": "text",
                    "quota_provider": "gpt",
                },
                "review-zai-provider": {
                    "argv": command + ["review"],
                    "stdin_prompt": True,
                    "parser": "text",
                    "quota_provider": "zai",
                },
            },
            "profiles": {
                "main": {
                    "role": "main",
                    "planner": "planner",
                    "allowed_providers": ["worker"],
                    "worker_profiles": ["worker-code"],
                    "reviewers": ["review-gpt", "review-zai"],
                    "max_plan_steps": 15,
                    "max_parallel": 15,
                    "queue_wait_seconds": 60,
                    "review_parallel": 2,
                    "review_policy": {"min_approvals": 2},
                },
                "worker-code": {
                    "role": "worker",
                    "provider": "worker",
                    "instructions": "SPECIALIST_MARKER: implement code and tests.",
                },
                "review-gpt": {
                    "role": "reviewer",
                    "provider": "review-gpt-provider",
                },
                "review-zai": {
                    "role": "reviewer",
                    "provider": "review-zai-provider",
                },
            },
            "rate_limits": {
                "gpt": {
                    "reserve_percent": 10,
                    "burst_percent": 5,
                    "unknown_policy": "deny",
                    "max_concurrency": 4,
                    "min_interval_seconds": 0,
                    "lease_seconds": 30,
                },
                "zai": {
                    "reserve_percent": 10,
                    "burst_percent": 5,
                    "unknown_policy": "deny",
                    "max_concurrency": 4,
                    "min_interval_seconds": 0,
                    "lease_seconds": 30,
                },
            },
            "rate_state_file": str(self.root / "rate.json"),
        }

    def test_plan_execute_review_e2e(self):
        with QuotaServer(quota_payload()) as server:
            harness = StarIntelLLMHarness(self.config(server.url), repo_root=ROOT)
            result = harness.run("build thing", wait_seconds=1)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["execution"]["steps"][0]["text"], "worker-ok")
        self.assertEqual([x["verdict"] for x in result["reviews"]], ["approve", "approve"])

    def test_quota_is_rechecked_after_local_admission(self):
        class SequencedLimiter:
            def __init__(self):
                self.calls = 0

            def check(self, provider_id):
                self.calls += 1
                if self.calls == 1:
                    return RateDecision(True, provider_id, "admitted")
                return RateDecision(False, provider_id, "reserve_floor", 120)

        with QuotaServer(quota_payload()) as server:
            harness = StarIntelLLMHarness(self.config(server.url), repo_root=ROOT)
            limiter = SequencedLimiter()
            harness.subscription = limiter

            dispatched = []
            harness._run_provider = lambda *args: dispatched.append(args)

            with self.assertRaises(HarnessError) as error:
                harness.call("worker", "do not dispatch")

        self.assertEqual(error.exception.code, "subscription_rate_limited")
        self.assertEqual(limiter.calls, 2)
        self.assertEqual(dispatched, [])

    def test_plan_step_limit_blocks_oversized_swarm(self):
        with QuotaServer(quota_payload()) as server:
            harness = StarIntelLLMHarness(self.config(server.url), repo_root=ROOT)
            plan = {
                "schema": "starintel.llm.plan.v1",
                "goal": "too many workers",
                "steps": [
                    {
                        "id": f"step-{index}",
                        "kind": "model",
                        "provider": "worker",
                        "agent_profile": "worker-code",
                        "prompt": "work",
                        "depends_on": [],
                    }
                    for index in range(16)
                ],
            }
            with self.assertRaises(HarnessError) as error:
                harness.execute(plan, "main", wait_seconds=1)
        self.assertEqual(error.exception.code, "plan_step_limit")

    def test_worker_profile_provider_mismatch_is_rejected(self):
        with QuotaServer(quota_payload()) as server:
            harness = StarIntelLLMHarness(self.config(server.url), repo_root=ROOT)
            plan = {
                "schema": "starintel.llm.plan.v1",
                "goal": "bad mapping",
                "steps": [{
                    "id": "step-1",
                    "kind": "model",
                    "provider": "review-zai-provider",
                    "agent_profile": "worker-code",
                    "prompt": "work",
                    "depends_on": [],
                }],
            }
            with self.assertRaises(HarnessError) as error:
                harness.execute(plan, "main", wait_seconds=1)
        self.assertIn(error.exception.code, {"plan_provider_not_allowed", "plan_worker_provider_mismatch"})

    def test_prolog_rejects_cycle(self):
        verifier = PrologVerifier(ROOT / "kb" / "core" / "star_llm_harness.pl")
        plan = {
            "schema": "starintel.llm.plan.v1",
            "goal": "cycle",
            "steps": [
                {
                    "id": "a",
                    "kind": "model",
                    "provider": "worker",
                    "prompt": "a",
                    "depends_on": ["b"],
                },
                {
                    "id": "b",
                    "kind": "model",
                    "provider": "worker",
                    "prompt": "b",
                    "depends_on": ["a"],
                },
            ],
        }
        with self.assertRaises(HarnessError):
            verifier.verify(plan)


if __name__ == "__main__":
    unittest.main()
