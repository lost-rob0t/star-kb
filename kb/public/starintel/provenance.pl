:- module(starintel_provenance,
          [ required_provenance_field/1,
            document_field/2,
            provenance_complete/1,
            provenance_violation/2,
            claim_source/3,
            independent_source_count/2,
            claim_status/2,
            empty_source_policy/1,
            migration_requirement/1,
            no_silent_data_loss/1
          ]).

:- dynamic document_field/2.
:- dynamic claim_source/3.

required_provenance_field(sources).
required_provenance_field(evidence).
required_provenance_field(uncertainty).
required_provenance_field(lineage).

provenance_complete(Doc) :-
    forall(required_provenance_field(Field),
           document_field(Doc, Field)).

provenance_violation(Doc, missing_field(Field)) :-
    required_provenance_field(Field),
    \+ document_field(Doc, Field).

independent_source_count(Claim, Count) :-
    aggregate_all(count, claim_source(Claim, _, independent), Count).

claim_status(Claim, attributed_claim) :-
    independent_source_count(Claim, Count),
    Count =< 1.
claim_status(Claim, corroborated_fact) :-
    independent_source_count(Claim, Count),
    Count >= 2.

empty_source_policy(visible_in_unverified_ledger).
empty_source_policy(not_hidden).
empty_source_policy(not_silently_dropped).

migration_requirement(preserve_unknown_legacy_values).
migration_requirement(preserve_migration_provenance).
migration_requirement(full_corpus_validation_after_migration).

no_silent_data_loss(unknown_legacy_values).
