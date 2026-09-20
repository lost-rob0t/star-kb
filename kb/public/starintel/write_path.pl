:- module(starintel_write_path,
          [ sanctioned_write/2,
            prohibited_write_method/1,
            draft_generator_permitted_for/1,
            draft_generator_forbidden_for/1,
            write_invariant/2,
            storage_rule/1,
            id_path_safe/1,
            storage_path/4,
            change_decision/4,
            deletion_requires/1,
            schema_change_requires/1,
            resolves_to_normalized_record/1,
            schema_unresolved_representation/1,
            endpoint_ok/1,
            dangling_endpoint/1
          ]).

:- dynamic resolves_to_normalized_record/1.
:- dynamic schema_unresolved_representation/1.

sanctioned_write(single_record, transactional_writer).
sanctioned_write(record_batch, validated_batch_importer).
sanctioned_write(relation_record, transactional_relation_writer).

prohibited_write_method(editor).
prohibited_write_method(heredoc).
prohibited_write_method(shell_capture).
prohibited_write_method(json_tool_redirection).
prohibited_write_method(ad_hoc_script).

draft_generator_permitted_for(inspection).
draft_generator_permitted_for(draft_outside_canonical_store).
draft_generator_forbidden_for(canonical_store_output).

write_invariant(transactional_writer, validates_document_before_write).
write_invariant(transactional_writer, writes_only_canonical_store_path).
write_invariant(transactional_writer, validates_full_corpus_after_write).
write_invariant(transactional_writer, rolls_back_on_invariant_failure).
write_invariant(validated_batch_importer, validates_input_outside_canonical_store).
write_invariant(validated_batch_importer, validates_full_corpus_after_write).
write_invariant(validated_batch_importer, replaces_only_for_intentional_correction).
write_invariant(validated_batch_importer, migrates_only_explicit_legacy_input).

storage_rule(directory_name_equals_dtype).
storage_rule(file_name_equals_id_plus_suffix).
storage_rule(single_compact_json_object_per_file).
storage_rule(exactly_one_trailing_newline).
storage_rule(no_path_separators_in_id).
storage_rule(no_duplicate_normalized_ids).

id_path_safe(Id) :-
    atom(Id),
    Id \= '',
    \+ sub_atom(Id, _, _, _, '/'),
    \+ sub_atom(Id, _, _, _, '\\').

storage_path(Root, Dtype, Id, Path) :-
    id_path_safe(Id),
    format(atom(Path), "~w/~w/~w.ndjson", [Root, Dtype, Id]).

change_decision(same_id, OldVersion, NewVersion, intentional_replacement) :-
    integer(OldVersion),
    integer(NewVersion),
    NewVersion > OldVersion.
change_decision(same_id, Version, Version, documented_correction).
change_decision(different_id, _, _, new_record).

deletion_requires(documented_reason).

schema_change_requires(migration).
schema_change_requires(full_corpus_validation).

endpoint_ok(Endpoint) :-
    resolves_to_normalized_record(Endpoint).
endpoint_ok(Endpoint) :-
    schema_unresolved_representation(Endpoint).

dangling_endpoint(Endpoint) :-
    \+ endpoint_ok(Endpoint).
