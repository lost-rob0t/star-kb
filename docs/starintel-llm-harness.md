# StarIntel LLM harness

`starintel-llm` is the profile-driven worker plane for StarIntel development and
symbolic work.

## Authority split

- **Star KB** owns the harness schema, Prolog plan validator, worker DAG
  execution, reviewer quorum, and subscription-aware admission algorithm.
- **Prolog-RLM** remains the reusable RLM/model runtime. The default dotfiles
  profile invokes it for GLM execution rather than reimplementing RLM semantics.
- **dotfiles** owns the live machine configuration, provider commands, local
  paths, llm-log routing, model selection, concurrency, and quota reserve.
- **llm-log** is the local transport/telemetry boundary. Its cached
  `/api/v1/quotas` response is the only subscription-meter input.
- Provider credentials stay in the provider's existing auth path. They are not
  copied into Star KB.

The default config path is:

```text
$STARINTEL_LLM_CONFIG
or
$XDG_CONFIG_HOME/starintel/llm-harness.json
```

## Default main-worker topology

The dotfiles integration installs this shape:

```text
Codex read-only planner
        |
        v
starintel.llm.plan.v1
        |
        v
SWI-Prolog structural verification
        |
        v
ready-step DAG executor
        |
        v
Prolog-RLM -> llm-log -> z.AI Coding Plan
        |
        +--> independent Codex reviewer
        +--> independent GLM reviewer
```

The alternative `main-direct-glm` profile uses `opencode-worker` for execution
while preserving the same planner, plan verifier, quota gate, and reviewers.

## Plan contract

A planner must return one typed object:

```json
{
  "schema": "starintel.llm.plan.v1",
  "mode": "plan",
  "goal": "implement the requested slice",
  "steps": [
    {
      "id": "implementation",
      "kind": "model",
      "provider": "prolog-rlm-glm",
      "prompt": "implement and test the slice",
      "depends_on": []
    }
  ]
}
```

`kb/core/star_llm_harness.pl` rejects empty plans, duplicate IDs, unknown/missing
dependencies, self dependencies, unsupported step kinds, and dependency cycles.
Python also enforces the main profile's provider allowlist before execution.

## Worker profiles

Profiles are data. A typical config defines:

- `main`: Codex planner, bounded worker fan-out, reviewer quorum;
- `main-direct-glm`: direct OpenCode/GLM executor;
- `worker-prolog-rlm`: GLM through Prolog-RLM;
- `worker-glm`: direct `opencode-worker`;
- `review-codex`: independent Codex review;
- `review-glm`: independent GLM review.

More worker/reviewer profiles can be added without changing harness code.

## Subscription pacing

The harness does **not** guess a quota from a plan name such as "Pro" or
"Max". It consumes provider-reported windows from llm-log.

Every active meter must admit the call.

For each known window:

```text
spendable = 100 - reserve_percent
elapsed   = elapsed_time / window_duration
ceiling   = min(spendable, spendable * elapsed + burst_percent)
```

Admission is rejected when:

- the provider/meter is missing, stale, expired, or unknown and policy is
  fail-closed;
- reported usage reaches the configured reserve floor;
- reported usage is ahead of the time-proportional budget curve;
- the cross-process concurrency limit is full;
- the per-provider launch interval has not elapsed.

This protects harness-originated work from consuming the entire observed plan
window early. It cannot guarantee capacity against traffic generated outside
the harness; the next quota observation incorporates that external usage.

## Commands

With dotfiles/Home Manager applied:

```sh
python3 -m prolog_star_kb.llm_harness profiles
python3 -m prolog_star_kb.llm_harness quota
python3 -m prolog_star_kb.llm_harness check-rate codex-plan
python3 -m prolog_star_kb.llm_harness plan --profile main "goal"
python3 -m prolog_star_kb.llm_harness run --profile main --wait-seconds 300 "goal"
```

The repo also provides `tools/starintel-llm`; installing/exposing that script as
an executable is a packaging concern rather than a second implementation.

Exit status `75` means admission/rate limiting prevented a provider call.

## Security properties

- provider commands are argv arrays and are never executed through a shell;
- Codex planning is configured read-only by dotfiles;
- generated plan text never becomes arbitrary Prolog source;
- the Prolog verifier reads JSON and validates a fixed schema;
- subscription state is read from a loopback-only HTTP endpoint;
- the quota HTTP client ignores ambient proxy settings and rejects redirects;
- shared local leases are file-locked across worker processes;
- credentials are inherited only by the provider command that already owns
  their normal runtime contract.

## Verification

```sh
python3 -m unittest tests.test_llm_harness -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

CI installs SWI-Prolog, so the E2E test exercises:

```text
fake planner -> real Prolog verification -> worker -> two reviewers
```

without paid credentials.
