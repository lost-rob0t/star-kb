# prolog-star-kb

`prolog-star-kb` is the StarIntel JSON -> Prolog reasoning projection.

The authoritative record remains canonical StarIntel JSON. The active StarIntel release is 0.9.1 while the immutable base schema remains 0.9.0; generated projections record release, base schema, profile, revision, and expansion hash so replay can identify the exact contract.

## Projection

```sh
tools/prolog-star-kb project corpus.ndjson -o kb/generated/corpus.pl
```

Every JSON object, array, member, index, scalar, and type is emitted using JSON-Pointer paths. Semantic indexes are emitted in addition to the lossless path facts:

- `star_doc/6`, `star_profile/5`
- `star_ref/3`
- `star_time/4`
- `star_source/7`, `star_evidence/7`, `star_provenance/9`
- `star_relation/9`, inverse predicates, and scalar qualifiers

Unknown/additive JSON fields are therefore preserved automatically instead of waiting for converter code to learn every field.

## AI tools

```sh
tools/prolog-star-kb tools
tools/prolog-star-kb goal kb_path '{"source":"starintel:person:a","target":"starintel:org:b","max_depth":5}'
```

The tool catalog exposes bounded semantic operations rather than arbitrary Prolog execution: document lookup, graph neighbors/path, relation explanation, timeline, contradictions, comparison, sources/provenance, why-not, arbitrary lossless JSON-path value lookup, reverse referrers, compact reasoning packets, and capability routing.

`kb_packet` is the RLM-friendly fast path: it returns a bounded bundle of identity, neighborhood, timeline, related sources/provenance, and contradictions. `kb_route_reasoning` returns a reasoning capability, not an engine name. Runtime policy can map deterministic rules, probabilistic queries, recursive tabled queries, explanation, and bulk Datalog closure to the selected engine.

## Trust boundary

Generated Prolog is a deterministic derivative of canonical JSON. It is rebuildable cache/index state, never an independent truth store. LLM/RLM output must enter StarIntel as candidate JSON with provenance before it can become part of a future projection.
