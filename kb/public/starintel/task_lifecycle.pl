:- module(starintel_task_lifecycle,
          [ task_requirement/1,
            artifact_requirement/2,
            task_artifact/2,
            provided/2,
            completion_surface/2,
            missing_requirement/2,
            task_complete/1,
            insufficient_evidence/2,
            canonical_surface/1
          ]).

:- dynamic task_artifact/2.
:- dynamic provided/2.
:- dynamic completion_surface/2.

task_requirement(canonical_surface_updated).
task_requirement(imported_through_canonical_path).

artifact_requirement(email_artifact, source_document).
artifact_requirement(email_artifact, typed_record(email_message)).
artifact_requirement(email_artifact, person_records(sender)).
artifact_requirement(email_artifact, person_records(recipients)).
artifact_requirement(email_artifact, person_records(explicit_body_names)).
artifact_requirement(email_artifact, relation_records(linking_participants_to_sources_and_persons)).

artifact_requirement(social_artifact, entity_records(observed_actors)).
artifact_requirement(social_artifact, relation_records(authorship)).
artifact_requirement(social_artifact, relation_records(reply_or_parent_structure)).
artifact_requirement(social_artifact, relation_records(mentions_or_links)).
artifact_requirement(social_artifact, relation_records(membership_or_community)).
artifact_requirement(social_artifact, single_canonical_entity_per_stable_identifier).
artifact_requirement(social_artifact, observation_provenance_preserved).

insufficient_evidence(email_artifact, image_only).
insufficient_evidence(email_artifact, source_record_only).
insufficient_evidence(email_artifact, generic_message_only).
insufficient_evidence(email_artifact, summary_only).
insufficient_evidence(email_artifact, investigation_target_only).
insufficient_evidence(social_artifact, embedded_scalar_authors_without_entities).
insufficient_evidence(social_artifact, posts_without_actor_nodes_or_relations).

canonical_surface(normalized_store).
canonical_surface(canonical_packet_documents).

missing_requirement(Task, Requirement) :-
    task_artifact(Task, _),
    task_requirement(Requirement),
    \+ provided(Task, Requirement).
missing_requirement(Task, Requirement) :-
    task_artifact(Task, ArtifactClass),
    artifact_requirement(ArtifactClass, Requirement),
    \+ provided(Task, Requirement).

task_complete(Task) :-
    task_artifact(Task, _),
    \+ missing_requirement(Task, _).
