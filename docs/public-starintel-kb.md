# Public StarIntel Rule Knowledge Base

Generalized, consumer-agnostic Prolog rules for StarIntel tasks: task completeness,
canonical write paths, identity safety, provenance, gate discipline, YAGNI-style rule
review, and the accepted rule-system improvement proposals.

Status: **proposed** research output (see `roam/research/star-kb/public-starintel-rules-research.org`).
Not yet owner-approved; load and critique it, do not treat it as binding policy.

Derived from the 2026-09-19 rule-system critique (`/tmp/opencode/dig-queue-2026-09-19/critique/rules-critique.md`,
`critique-facts.pl`), which reviewed the auto-dig repository law and global agent policy.
The rules here are **general**: parametric over repository/consumer, with no auto-dig
paths, nix-store paths, or dataset names baked in. Canonical StarIntel JSON stays
authoritative — this KB is rule/policy knowledge, not data.

## Module map

| Module | Covers | Key predicates |
|--------|--------|----------------|
| `task_lifecycle.pl` | When a pass/task is complete | `task_complete/1`, `missing_requirement/2`, `artifact_requirement/2`, `insufficient_evidence/2` |
| `write_path.pl` | Canonical write-path invariants | `sanctioned_write/2`, `prohibited_write_method/1`, `storage_path/4`, `id_path_safe/1`, `change_decision/4`, `dangling_endpoint/1` |
| `identity_safety.pl` | No force-merge of ambiguous identities | `merge_permitted/2`, `merge_forbidden/2`, `entity_for_observation/3`, `observation_divergence/4`, `candidate_link_requirement/1` |
| `provenance.pl` | Sources, uncertainty, lineage, claims vs facts | `provenance_complete/1`, `provenance_violation/2`, `claim_status/2`, `empty_source_policy/1` |
| `gate_discipline.pl` | Fail-closed control plane, merge gate, gate cadence | `work_authorized/1`, `merge_permitted/1`, `stale_evidence/1`, `recommended_gate_point/1`, `norm/2` |
| `yagni_review.pl` | Queryable rule-review checklist | `ceremonial_candidate/1`, `deletion_trap/1`, `safe_delete/1`, `verdict_rule/2`, `unenforced_safety_claim/1` |
| `iq_improvements.pl` | Improvement proposals as facts | `proposal/2`, `proposal_status/2`, `finding_disposition/2`, `iq_principle/1`, `tension_resolution/3` |

Dynamic predicates (`provided/2`, `claim_source/3`, `rule_profile/3`,
`validation_outcome_recorded/2`, ...) are assertion points: the consumer projects its
own task/tool state onto them, then queries the rules.

## Loading

One loader re-exports everything:

```sh
swipl -q -s kb/public/starintel/starintel_public.pl
```

Or per module:

```prolog
:- use_module('kb/public/starintel/gate_discipline').
```

## Example queries (recorded answers, swipl 10.0.2)

```prolog
% Ambiguous identities are never force-merged.
?- assertz(starintel_identity_safety:ambiguous_candidate(a, b)),
   starintel_identity_safety:merge_forbidden(a, b).
true.

% A stable source identifier resolves to exactly one source-scoped entity.
?- setof(E, starintel_identity_safety:entity_for_observation(src1, handle_x, E), Es).
Es = [e1].          % after assertz(stable_identifier(src1, handle_x, e1))

% Claims graduate only with two independent sources.
?- starintel_provenance:claim_status(c2, S).   % c2 has sources s1,s2 independent
S = corroborated_fact.

% Control plane authorizes only enabled+running; third states are blocked.
?- starintel_gate_discipline:work_blocked(control(enabled, draining)).
true.

% Merge requires passing validation + exact-head evidence + a ran gate.
?- starintel_gate_discipline:merge_decision(pr_stale, D).  % evidence head != current head
D = blocked.

% Recommended gate cadence: boundaries, not per-import steps.
?- setof(B, starintel_gate_discipline:recommended_gate_point(B), Bs).
Bs = [integration_merge, pass_end].
?- starintel_gate_discipline:redundant_gate_point(single_import).
true.

% Email task completeness is checkable and diagnosable.
?- starintel_task_lifecycle:missing_requirement(t2, M).  % unprovisioned email task
M = person_records(recipients) ;   % ...8 missing requirements enumerated.

% The review checklist ranks a known ceremonial rule as a candidate.
?- starintel_yagni_review:ceremonial_candidate(per_import_gate_rerun).  % cost high, prevents nothing
true.
?- starintel_yagni_review:verdict_rule(control_plane_gate, V).          % cost low, prevents phantom state
V = keep.

% Proposals are minted as facts, still proposed (RAGE: no self-approval).
?- findall(P, starintel_iq_improvements:proposal_status(P, proposed), Ps), length(Ps, N).
N = 15.
```

## Gate cadence rule (recommended policy)

The critique's highest-leverage finding, encoded in `gate_discipline.pl` as a
recommended rule rather than a repo change:

- one canonical gate command and one evidence ledger (never two parallel ledgers for
  the same "validation ran" fact);
- gate runs at **pass end** and **integration merge** — the transactional writer and
  importer already validate the full corpus per write, so a per-import gate rerun
  re-validates an unchanged corpus (`redundance_reason/2`);
- the conservative half of the tension is kept: writer-side full-corpus validation
  stays; only the gate-side repetition moves (`tension_resolution/3`).

## Consumers

- Assert your task/tool state into the dynamic predicates, then query.
- `tests/test_public_starintel_kb.py` skips cleanly when `swipl` is absent and shows
  runnable synthetic cases for every module.
