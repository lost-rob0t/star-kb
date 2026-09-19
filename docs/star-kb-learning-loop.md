# Star KB actor learning loop

This slice turns Star KB into a replayable actor-facing learning system without making an LLM an authority.

## Dataflow

```text
research text / bulk dataset
        |
        v
research-ingest actor (LLM or deterministic extractor)
        |
        v
candidate canonical StarIntel JSON
        |
        +----> reviewer / auditor / voter actors
        |             |
        |             v
        |        append-only votes
        |
        +----> query log <---- normal KB use
        |             |
        |             v
        |       review-context packets
        |             |
        |      auditor / optimizer actors
        |             |
        |             v
        |      improvement proposals
        |
        v
formal Prolog verification
        |
     verified
        |
        v
promotion by a separate canonical-JSON write path
```

The verifier decides whether a candidate satisfies the exact StarLang spec identity,
canonical StarIntel schema version, provenance requirements, evidence requirements,
and voting policy. A vote is evidence for admission; it is not proof by itself.

## Source of truth

`spec/star-kb-learning.star` and `spec/actors/*.star` are the protocol source.
StarLang parses and compiles them. Downstream Python, TypeScript, Common Lisp, Nim,
or other bindings consume StarLang compiler manifests; they must not maintain a
parallel hand-written semantic schema.

Star KB itself does not parse `.star` files. `star-kb-actors spec-check` delegates
validation to the StarLang compiler.

## CLI

```sh
tools/star-kb-actors init

tools/star-kb-actors submit candidate.json \
  --actor extractor-a --run-id run-001

tools/star-kb-actors vote starintel:relation:r1 \
  --actor reviewer-a --stance approve --weight 1000 --run-id run-002

tools/star-kb-actors query-log \
  --actor query-agent \
  --query "show related entities" \
  --tool kb_neighbors \
  --arguments '{"id":"starintel:person:a"}' \
  --result-ids '["starintel:relation:r1"]' \
  --run-id query-001

tools/star-kb-actors context --candidate starintel:relation:r1 --max-events 200

tools/star-kb-actors verify starintel:relation:r1 \
  --run-id verify-001 \
  --min-approvals 2 \
  --min-total-votes 2 \
  --approval-ratio 0.6666666667
```

For very large LLM-generated datasets, stage NDJSON in a streaming pass:

```sh
tools/star-kb-actors submit-batch generated.ndjson \
  --actor dataset-generator --run-id dataset-2026-09-18
```

This records candidates without loading the whole dataset in memory. Verification
and promotion remain independent gates.

## Voting semantics

Only the latest vote per voter is active during replay. Historical votes remain in
the event log. Formal verification checks:

- exact `specId` and `specVersion` adherence;
- exact required StarIntel schema version;
- candidate/generated status only;
- provenance actor, run ID, and method;
- minimum source and evidence counts;
- evidence source references resolve inside the candidate;
- valid vote stances and bounded integer weights;
- minimum approval count and total voter count;
- weighted approval ratio;
- self-vote exclusion by default.

LLM consensus cannot override a failed formal check. Every formal decision is appended back to the event log as a verification certificate so later audits can replay the decision history.

## Query-log learning

Every `query-log` event can preserve the original query, bounded tool arguments,
result identifiers, and a result hash. `context` creates a replayable review packet
for reviewer, auditor, and optimizer actors. Those actors may propose:

- new predicates or indexes;
- missing evidence collection;
- contradiction rules;
- query routing changes;
- new tests;
- dataset cleanup;
- spec revisions.

Such output is candidate knowledge or an improvement proposal until it passes the
appropriate review and verification gate.
