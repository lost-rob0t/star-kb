# prolog-star-kb

`prolog-star-kb` is the StarIntel JSON -> Prolog reasoning projection.

The authoritative record remains canonical StarIntel JSON. The active StarIntel release is 0.9.1 while the immutable base schema remains 0.9.0; generated projections record release, base schema, profile, revision, and expansion hash so replay can identify the exact contract.

## Projection

```sh
tools/prolog-star-kb project corpus.ndjson -o kb/generated/corpus.pl\n# Follow a newer additive release/profile explicitly:\ntools/prolog-star-kb project corpus.ndjson --manifest schemas/starintel-doc-v0.9.0.manifest.json -o kb/generated/corpus.pl
```

Every JSON object, array, member, index, scalar, and type is emitted using JSON-Pointer paths. Semantic indexes are emitted in addition to the lossless path facts:

- `star_doc/6`, `star_projection_input_hash/3`, `star_profile/5`
- `star_ref/3`
- `star_time/4`
- `star_source/7`, `star_evidence/7`, `star_provenance/9`
- `star_relation/9`, inverse predicates, and scalar qualifiers

Unknown/additive JSON fields are therefore preserved automatically instead of waiting for converter code to learn every field. `star_doc/6` preserves the document's declared canonical `content_hash` when present; `star_projection_input_hash/3` separately hashes the exact projector input so replay integrity is not confused with canonical document identity.

## AI tools

```sh
tools/prolog-star-kb tools
tools/prolog-star-kb goal kb_path '{"source":"starintel:person:a","target":"starintel:org:b","max_depth":5}'
```

The tool catalog exposes bounded semantic operations rather than arbitrary Prolog execution: document lookup, graph neighbors/path, relation explanation, timeline, contradictions, comparison, sources/provenance, why-not, arbitrary lossless JSON-path value lookup, reverse referrers, compact reasoning packets, and capability routing.

`kb_packet` is the RLM-friendly fast path: it returns a bounded bundle of identity, neighborhood, timeline, related sources/provenance, and contradictions. `kb_route_reasoning` returns a reasoning capability, not an engine name. Runtime policy can map deterministic rules, probabilistic queries, recursive tabled queries, explanation, and bulk Datalog closure to the selected engine.

## Trust boundary

Generated Prolog is a deterministic derivative of canonical JSON. It is rebuildable cache/index state, never an independent truth store. LLM/RLM output must enter StarIntel as candidate JSON with provenance before it can become part of a future projection.


## Long-term evidence maturity

star_longterm adds a durable, bounded layer for reasoning about the maturity of
explicit canonical links without inventing missing identity relationships.

The five maturity levels are:

1. `referenced` — a direct canonical `star_ref/3`.
2. `asserted` — a non-negated canonical relation exists.
3. `sourced` — the relation carries at least one source or evidence record.
4. `corroborated` — the relation carries at least two distinct sources and two evidence records.
5. `verified` — the relation has verified/confirmed evidence or qualifiers plus source/evidence support.

These levels describe the evidence state of a relation. They are not person,
risk, intent, guilt, or trust scores.

New bounded tools:

- `kb_relation_maturity` — explain all explicit assertions for a subject/predicate/object triple.
- `kb_linkage_neighbors` — list direct explicit relations/references filtered by maturity level.
- `kb_fact_history` — return bounded temporal observations for an entity and relation documents that reference it.

Contradicting canonical relations/evidence are surfaced as `contested(true)`;
they are never silently collapsed into one answer.
