from __future__ import annotations

import fcntl
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_QUOTA_BYTES = 262_144


class RateLimitError(RuntimeError):
    def __init__(self, code: str, detail: str = "", retry_after: float = 0.0):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.retry_after = max(0.0, float(retry_after))


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    provider: str
    reason: str
    retry_after: float = 0.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RateLimitError("quota_redirect_rejected", newurl)


def _loopback(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RateLimitError("quota_url_not_loopback", url)
    return url.rstrip("/")


class QuotaClient:
    """Read llm-log's cached provider quota snapshot without triggering provider work."""

    def __init__(self, base_url: str, timeout: float = 3.0):
        self.base_url = _loopback(base_url)
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def snapshot(self) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/api/v1/quotas",
            headers={"Accept": "application/json", "Connection": "close"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_QUOTA_BYTES + 1)
        except RateLimitError:
            raise
        except OSError as exc:
            raise RateLimitError("quota_api_unavailable", str(exc), 30) from exc

        if len(raw) > MAX_QUOTA_BYTES:
            raise RateLimitError("quota_response_too_large", retry_after=60)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise RateLimitError("quota_response_invalid", retry_after=60) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise RateLimitError("quota_schema_unsupported", retry_after=60)
        return payload


def _provider(snapshot: dict[str, Any], provider_id: str) -> dict[str, Any]:
    providers = snapshot.get("providers")
    if not isinstance(providers, list):
        raise RateLimitError("quota_providers_missing", retry_after=60)
    for item in providers:
        if isinstance(item, dict) and item.get("id") == provider_id:
            return item
    raise RateLimitError("quota_provider_missing", provider_id, 60)


def _window_decision(window: dict[str, Any], policy: dict[str, Any], now: float) -> RateDecision:
    state = window.get("state")
    used = window.get("used_percent")
    if state != "ok" or isinstance(used, bool) or not isinstance(used, (int, float)):
        if policy.get("unknown_policy", "deny") == "allow":
            return RateDecision(True, "", "unknown_allowed")
        return RateDecision(
            False,
            "",
            f"meter_{state or 'unknown'}",
            float(policy.get("unknown_retry_seconds", 60)),
        )

    used = float(used)
    reserve = float(policy.get("reserve_percent", 10))
    burst = float(policy.get("burst_percent", 5))
    if not math.isfinite(used) or not 0 <= used <= 100:
        return RateDecision(False, "", "meter_invalid", 60)
    if not 0 <= reserve < 100 or not 0 <= burst <= 100:
        raise RateLimitError("rate_policy_invalid")

    spendable = 100.0 - reserve
    reset = window.get("resets_at")
    duration = window.get("window_seconds")

    if used >= spendable:
        retry = max(1.0, float(reset) - now) if isinstance(reset, (int, float)) else 60.0
        return RateDecision(False, "", "reserve_floor", retry)

    if not isinstance(reset, (int, float)) or not isinstance(duration, (int, float)) or duration <= 0:
        return RateDecision(True, "", "hard_ceiling_only")

    start = float(reset) - float(duration)
    elapsed = max(0.0, min(1.0, (now - start) / float(duration)))
    ceiling = min(spendable, spendable * elapsed + burst)
    if used <= ceiling:
        return RateDecision(True, "", "paced")

    needed = max(0.0, min(1.0, (used - burst) / spendable))
    retry_at = start + needed * float(duration)
    return RateDecision(False, "", "ahead_of_budget_curve", max(1.0, retry_at - now))


class SubscriptionLimiter:
    """Admission control from provider-reported subscription windows.

    Every reported window must admit a call. The reserve floor preserves configured
    headroom; the time curve prevents burning a multi-hour or weekly bucket early.
    """

    def __init__(self, client: QuotaClient, policies: dict[str, Any]):
        self.client = client
        self.policies = policies

    def check(self, provider_id: str, now: float | None = None) -> RateDecision:
        policy = self.policies.get(provider_id)
        if not isinstance(policy, dict):
            raise RateLimitError("rate_policy_missing", provider_id)

        provider = _provider(self.client.snapshot(), provider_id)
        if provider.get("state") != "ok":
            return RateDecision(
                False,
                provider_id,
                f"provider_{provider.get('state') or 'unknown'}",
                float(policy.get("unknown_retry_seconds", 60)),
            )

        windows = provider.get("windows")
        if not isinstance(windows, list) or not windows:
            return RateDecision(False, provider_id, "no_quota_windows", 60)

        now = time.time() if now is None else now
        blocked: list[RateDecision] = []
        for window in windows:
            if not isinstance(window, dict):
                blocked.append(RateDecision(False, provider_id, "invalid_window", 60))
                continue
            decision = _window_decision(window, policy, now)
            if not decision.allowed:
                blocked.append(decision)

        if blocked:
            reasons = ",".join(sorted({item.reason for item in blocked}))
            return RateDecision(
                False,
                provider_id,
                reasons,
                max(item.retry_after for item in blocked),
            )
        return RateDecision(True, provider_id, "admitted")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class LocalLeaseLimiter:
    """Cross-process concurrency/min-interval limiter for local worker swarms."""

    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def acquire(
        self,
        key: str,
        *,
        max_concurrency: int,
        min_interval_seconds: float,
        lease_seconds: float,
        wait_seconds: float = 0,
    ) -> str:
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            try:
                return self._try_acquire(
                    key,
                    max_concurrency=max_concurrency,
                    min_interval_seconds=min_interval_seconds,
                    lease_seconds=lease_seconds,
                )
            except RateLimitError as exc:
                if exc.code != "local_rate_limited" or time.monotonic() >= deadline:
                    raise
                time.sleep(min(1.0, max(0.05, exc.retry_after)))

    def _try_acquire(
        self,
        key: str,
        *,
        max_concurrency: int,
        min_interval_seconds: float,
        lease_seconds: float,
    ) -> str:
        if max_concurrency < 1 or min_interval_seconds < 0 or lease_seconds <= 0:
            raise RateLimitError("local_rate_policy_invalid", key)

        token = str(uuid.uuid4())
        now = time.time()
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            try:
                state = json.load(stream)
            except ValueError:
                state = {}
            if not isinstance(state, dict):
                state = {}

            entries = state.get(key)
            if not isinstance(entries, list):
                entries = []
            live = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                pid = entry.get("pid")
                started = entry.get("started")
                if not isinstance(pid, int) or not isinstance(started, (int, float)):
                    continue
                if now - float(started) > lease_seconds or not _pid_alive(pid):
                    continue
                live.append(entry)

            if len(live) >= max_concurrency:
                retry = min(max(0.1, lease_seconds - (now - float(x["started"]))) for x in live)
                raise RateLimitError("local_rate_limited", f"{key}: concurrency", retry)

            last_started = max((float(x["started"]) for x in live), default=0.0)
            gap = min_interval_seconds - (now - last_started)
            if gap > 0:
                raise RateLimitError("local_rate_limited", f"{key}: interval", gap)

            live.append({"token": token, "pid": os.getpid(), "started": now})
            state[key] = live
            stream.seek(0)
            stream.truncate()
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        return token

    def release(self, key: str, token: str) -> None:
        if not self.path.exists():
            return
        with self.path.open("r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                state = json.load(stream)
            except ValueError:
                return
            entries = state.get(key)
            if not isinstance(entries, list):
                return
            state[key] = [
                item for item in entries
                if not (isinstance(item, dict) and item.get("token") == token)
            ]
            stream.seek(0)
            stream.truncate()
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
