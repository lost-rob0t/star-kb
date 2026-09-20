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
- `star_source/7`, `star_evidence/7`, `star_evidence_locator/3`, `star_provenance/9`
- `star_relation/9`, inverse predicates, and scalar qualifiers
- `star_relation_unresolved_endpoint/4` for relation endpoints the source explicitly marks unresolved

Unknown/additive JSON fields are therefore preserved automatically instead of waiting for converter code to learn every field. `star_doc/6` preserves the document's declared canonical `content_hash` when present; `star_projection_input_hash/3` separately hashes the exact projector input so replay integrity is not confused with canonical document identity.

NDJSON input is projected with constant memory in input order (use sorted input for canonical ordering), so whole-corpus jobs stay bounded. Duplicate `_id` values in one projection fail closed. Evidence entries without an `evidence_id` and source entries without a `source_id` are indexed under deterministic content-hash synthetic keys (`ev:…`, `src:…`) so their provenance stays queryable without inventing canonical identities. The generated header declares the projection predicates `discontiguous`, keeping large corpus loads quiet and fast in SWI-Prolog.

## Fact-shape mining

```sh
tools/prolog-star-kb mine-shapes corpus.ndjson -o shapes.pl --json shapes.json
```

`mine-shapes` deterministically mines the observed fact shapes of a corpus and emits them as versioned Prolog facts (loadable with `kb/core/star_shapes.pl`) plus an optional `starintel.shapes.v1` JSON sidecar:

- `star_shape_manifest/4` — miner version, corpus hash, doc count, dtype count; no timestamps, so identical corpora give byte-identical output
- `star_dtype_count/2`
- `star_field_shape/5`, `star_field_cardinality/4`, `star_field_exemplar/3` — per dtype and normalized JSON path shape (array indexes collapse to `#`)
- `star_relation_shape/4` — predicate plus subject/object domain shapes such as `person -> org` or `unresolved`
- `star_qualifier_shape/4`
- `star_temporal_key/3`
- `star_ref_shape/3` — observed cross-dtype reference directions

Mined shapes are candidate ontology evidence derived from canonical JSON, never trusted truth.

## AI tools

```sh
tools/prolog-star-kb tools
tools/prolog-star-kb goal kb_path '{"source":"starintel:person:a","target":"starintel:org:b","max_depth":5}'
```

The tool catalog exposes bounded semantic operations rather than arbitrary Prolog execution: document lookup, graph neighbors/path, relation explanation, timeline, contradictions, comparison, sources/provenance, why-not, arbitrary lossless JSON-path value lookup, reverse referrers, compact reasoning packets, and capability routing.

`kb_packet` is the RLM-friendly fast path: it returns a bounded bundle of identity, neighborhood, timeline, related sources/provenance, and contradictions. `kb_route_reasoning` returns a reasoning capability, not an engine name. Runtime policy can map deterministic rules, probabilistic queries, recursive tabled queries, explanation, and bulk Datalog closure to the selected engine.

## Trust boundary

Generated Prolog is a deterministic derivative of canonical JSON. It is rebuildable cache/index state, never an independent truth store. LLM/RLM output must enter StarIntel as candidate JSON with provenance before it can become part of a future projection.
