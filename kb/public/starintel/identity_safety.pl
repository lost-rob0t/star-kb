:- module(starintel_identity_safety,
          [ identity_confirmed/3,
            ambiguous_candidate/2,
            contradicting_identity_evidence/2,
            merge_permitted/2,
            merge_forbidden/2,
            stable_identifier/3,
            entity_for_observation/3,
            observation_divergence/4,
            person_record_required/1,
            person_record_forbidden/1,
            unresolved_person_rule/2,
            candidate_link_requirement/1,
            body_statement_status/1,
            entity_creation_asserts_real_world_identity/1
          ]).

:- dynamic identity_confirmed/3.
:- dynamic ambiguous_candidate/2.
:- dynamic contradicting_identity_evidence/2.
:- dynamic stable_identifier/3.

merge_permitted(A, B) :-
    identity_confirmed(A, B, _),
    \+ ambiguous_candidate(A, B),
    \+ ambiguous_candidate(B, A),
    \+ contradicting_identity_evidence(A, B),
    \+ contradicting_identity_evidence(B, A).

merge_forbidden(A, B) :-
    \+ merge_permitted(A, B).

entity_for_observation(Source, StableId, Entity) :-
    stable_identifier(Source, StableId, Entity).

observation_divergence(Source, StableId, Entity1, Entity2) :-
    stable_identifier(Source, StableId, Entity1),
    stable_identifier(Source, StableId, Entity2),
    Entity1 \= Entity2.

person_record_required(unresolved_displayed_name).
person_record_forbidden(guess_legal_identity).
person_record_forbidden(merge_ambiguous_name_into_existing_person).

unresolved_person_rule(scope, source_scoped).
unresolved_person_rule(merge, forbidden_until_confirmed).

candidate_link_requirement(preserve_evidence).
candidate_link_requirement(preserve_confidence).
candidate_link_requirement(preserve_contradictions).
candidate_link_requirement(preserve_alternate_hypotheses).
candidate_link_requirement(no_force_merge).

body_statement_status(attributed_claim_until_corroborated).

entity_creation_asserts_real_world_identity(false).
