:- module(starintel_iq_improvements,
          [ iq_principle/1,
            principle_rationale/2,
            principle_effect/2,
            proposal/2,
            proposal_source/2,
            proposal_status/2,
            proposal_target/2,
            proposal_rationale/2,
            proposal_effect/2,
            proposal_tension/3,
            tension_resolution/3,
            finding_disposition/2,
            disposition_reason/2,
            open_question/1,
            finding_execution/2
          ]).

iq_principle(gate_at_boundaries_not_steps).
iq_principle(one_ledger_per_fact).
iq_principle(one_entrypoint_per_operation).
iq_principle(prefer_enforcement_over_prose).
iq_principle(derive_displayed_text_from_authority).
iq_principle(fail_closed_once_not_repeatedly).
iq_principle(norms_general_registries_specific).
iq_principle(ceremony_budget).
iq_principle(no_pinned_paths_for_moving_dependencies).
iq_principle(no_silent_empty_results).
iq_principle(policy_must_be_enforceable_in_target_runtime).
iq_principle(contract_must_match_tool_surface).

principle_rationale(gate_at_boundaries_not_steps,
    'writer_side_validation_covers_intra_pass_drift_so_stepwise_gates_revalidate_an_unchanged_corpus').
principle_rationale(one_ledger_per_fact,
    'recording_the_same_validation_fact_twice_costs_tokens_and_invites_divergent_answers').
principle_rationale(one_entrypoint_per_operation,
    'parallel_entrypoints_for_one_operation_are_pure_drift_surface').
principle_rationale(prefer_enforcement_over_prose,
    'a_total_mechanism_beats_exhortation_where_it_is_cheaper_than_the_prose_it_replaces').
principle_rationale(derive_displayed_text_from_authority,
    'hand_copied_literals_drift_from_the_authority_that_owns_them').
principle_rationale(fail_closed_once_not_repeatedly,
    'the_control_plane_check_costs_seconds_and_prevents_phantom_work').
principle_rationale(norms_general_registries_specific,
    'incident_driven_statutes_overfit_a_general_norm_that_a_registry_already_expresses').
principle_rationale(ceremony_budget,
    'write_cost_above_reuse_value_discourages_writing_knowledge_down_at_all').
principle_rationale(no_pinned_paths_for_moving_dependencies,
    'content_addressed_paths_for_moving_dependencies_become_the_outage').
principle_rationale(no_silent_empty_results,
    'an_empty_answer_for_an_ambiguous_query_is_indistinguishable_from_exhausted_leads').
principle_rationale(policy_must_be_enforceable_in_target_runtime,
    'unenforceable_policy_invites_accidental_violation_and_teaches_agents_to_ignore_policy').
principle_rationale(contract_must_match_tool_surface,
    'a_contract_that_names_fewer_writers_than_exist_on_disk_erodes_the_rule_it_states').

principle_effect(gate_at_boundaries_not_steps,
    'saves_roughly_imports_minus_one_times_gate_cost_per_pass_with_identical_coverage').
principle_effect(one_ledger_per_fact,
    'one_authority_for_what_validation_ran_minutes_and_tokens_saved_per_task').
principle_effect(one_entrypoint_per_operation,
    'agents_stop_guessing_which_of_several_identical_tools_is_canonical').
principle_effect(prefer_enforcement_over_prose,
    'converts_hope_into_mechanism_and_removes_a_class_of_undetectable_violations').
principle_effect(derive_displayed_text_from_authority,
    'removes_active_misinformation_that_contradicts_the_authority_chain').
principle_effect(fail_closed_once_not_repeatedly,
    'keeps_phantom_work_prevention_at_seconds_per_run_cost').
principle_effect(norms_general_registries_specific,
    'keeps_the_norm_while_making_the_specific_cases_machine_checkable').
principle_effect(ceremony_budget,
    'shared_facts_get_written_more_often_because_writing_them_cost_less').
principle_effect(no_pinned_paths_for_moving_dependencies,
    'bootstraps_survive_dependency_upgrades_without_editing_law').
principle_effect(no_silent_empty_results,
    'prevents_wasted_passes_and_false_exhausted_leads_stop_conditions').
principle_effect(policy_must_be_enforceable_in_target_runtime,
    'policy_and_runtime_stop_contradicting_each_other').
principle_effect(contract_must_match_tool_surface,
    'agents_discover_the_real_sanctioned_surface_instead_of_dead_parallel_paths').

proposal(p01, gate_cadence).
proposal(p02, single_gate_command_and_evidence_ledger).
proposal(p03, enforce_or_delete_permission_bits).
proposal(p04, single_cli_entrypoint_per_operation).
proposal(p05, derive_version_text_from_authority).
proposal(p06, retire_unsanctioned_generators).
proposal(p07, dynamic_dependency_resolution).
proposal(p08, warn_on_ambiguous_query_empty_frontier).
proposal(p09, migration_commands_track_authority_line).
proposal(p10, canonical_root_registry_instead_of_statutes).
proposal(p11, trim_memory_ceremony_to_provenance_core).
proposal(p12, document_the_real_sanctioned_surface).
proposal(p13, prose_aligns_to_fail_closed_checker).
proposal(p14, scope_discovery_policy_to_enforcing_runtimes).
proposal(p15, enforce_output_target_restrictions).

proposal_source(p01, f03).
proposal_source(p02, f04).
proposal_source(p03, f02).
proposal_source(p04, f07).
proposal_source(p05, f08).
proposal_source(p06, f06).
proposal_source(p07, f11).
proposal_source(p08, f15).
proposal_source(p09, f09).
proposal_source(p10, f10).
proposal_source(p11, f19).
proposal_source(p12, f22).
proposal_source(p13, f14).
proposal_source(p14, f21).
proposal_source(p15, f16).

proposal_status(P, proposed) :- proposal(P, _).

proposal_target(p01, general_policy).
proposal_target(p02, general_policy).
proposal_target(p03, general_policy).
proposal_target(p04, consumer_repo).
proposal_target(p05, consumer_repo).
proposal_target(p06, consumer_repo).
proposal_target(p07, general_policy).
proposal_target(p08, consumer_repo).
proposal_target(p09, consumer_repo).
proposal_target(p10, general_policy).
proposal_target(p11, general_policy).
proposal_target(p12, consumer_repo).
proposal_target(p13, general_policy).
proposal_target(p14, general_policy).
proposal_target(p15, consumer_repo).

proposal_rationale(p01,
    'the_transactional_writer_and_importer_already_validate_the_full_corpus_after_writing').
proposal_rationale(p02,
    'two_evidence_ledgers_record_the_same_what_command_ran_fact_in_two_places_one_outside_the_repo').
proposal_rationale(p03,
    'five_permission_bits_are_declared_and_none_are_enforced_which_creates_false_safety').
proposal_rationale(p04,
    'six_identical_shims_wrap_the_same_cli_main_one_subcommand_each').
proposal_rationale(p05,
    'cli_banner_and_help_literals_contradict_the_authority_chain_the_repo_declares_authoritative').
proposal_rationale(p06,
    'about_half_of_the_scripts_tree_are_subject_one_offs_predating_the_mandated_write_path').
proposal_rationale(p07,
    'a_content_addressed_dependency_path_rots_at_the_next_upgrade_and_becomes_the_failure').
proposal_rationale(p08,
    'a_multi_subject_query_silently_emits_an_empty_frontier_indistinguishable_from_no_targets').
proposal_rationale(p09,
    'the_documented_migrator_targets_a_retired_line_while_the_authority_has_advanced').
proposal_rationale(p10,
    'a_general_dataset_root_rule_was_overfit_with_one_company_specific_statute').
proposal_rationale(p11,
    'ten_mandatory_properties_per_shared_fact_cost_more_than_the_fact_is_reused').
proposal_rationale(p12,
    'the_contract_names_two_writers_while_disk_ships_about_five_write_import_paths').
proposal_rationale(p13,
    'prose_blocks_only_paused_while_the_checker_requires_running_for_third_states_they_disagree').
proposal_rationale(p14,
    'brave_only_discovery_is_mandated_in_a_runtime_that_exposes_no_brave_tool').
proposal_rationale(p15,
    'a_prose_ban_on_an_output_flag_is_enforceable_totally_by_two_lines_of_code').

proposal_effect(p01,
    'saves_roughly_imports_minus_one_times_gate_cost_per_multi_import_pass').
proposal_effect(p02,
    'one_evidence_authority_shared_by_merge_gate_and_global_verification_policy').
proposal_effect(p03,
    'unenforced_safety_claims_become_real_enforcement_or_disappear').
proposal_effect(p04,
    'one_discoverable_entrypoint_drift_surface_collapses').
proposal_effect(p05,
    'self_describing_tools_stop_contradicting_the_version_authority').
proposal_effect(p06,
    'agent_search_space_over_scripts_shrinks_by_about_half').
proposal_effect(p07,
    'fresh_worktree_bootstraps_survive_dependency_bumps').
proposal_effect(p08,
    'wasted_passes_and_false_exhausted_leads_stop_conditions_disappear').
proposal_effect(p09,
    'migration_text_and_authority_chain_stop_disagreeing').
proposal_effect(p10,
    'the_norm_stays_machine_checkable_the_statute_goes').
proposal_effect(p11,
    'shared_facts_cost_less_to_write_so_more_get_written').
proposal_effect(p12,
    'contract_and_disk_stop_disagreeing_about_sanctioned_writers').
proposal_effect(p13,
    'prose_guided_agents_stop_proceeding_in_third_states').
proposal_effect(p14,
    'policy_stops_being_accidentally_violated_by_its_own_runtime').
proposal_effect(p15,
    'the_banned_output_path_becomes_unreachable_instead_of_discouraged').

proposal_tension(p01, yagni_gate_once, conservative_keep_writer_side_validation).
proposal_tension(p02, yagni_one_ledger, conservative_keep_one_tamper_evident_ledger).
proposal_tension(p10, yagni_general_norm_only, conservative_keep_incident_norm).

tension_resolution(yagni_gate_once, conservative_keep_writer_side_validation,
    'keep_the_writer_side_full_corpus_validation_move_only_the_gate_side_repetition').
tension_resolution(yagni_one_ledger, conservative_keep_one_tamper_evident_ledger,
    'collapse_to_one_repo_owned_ledger_so_at_least_one_tamper_evident_ledger_remains').
tension_resolution(yagni_general_norm_only, conservative_keep_incident_norm,
    'keep_the_norm_as_a_general_rule_back_it_with_a_checked_in_registry').

finding_disposition(f01, keep).
finding_disposition(f02, accepted).
finding_disposition(f03, accepted).
finding_disposition(f04, accepted).
finding_disposition(f05, keep).
finding_disposition(f06, accepted).
finding_disposition(f07, accepted).
finding_disposition(f08, accepted).
finding_disposition(f09, accepted).
finding_disposition(f10, accepted).
finding_disposition(f11, accepted).
finding_disposition(f12, keep).
finding_disposition(f13, keep).
finding_disposition(f14, accepted).
finding_disposition(f15, accepted).
finding_disposition(f16, accepted).
finding_disposition(f17, keep).
finding_disposition(f18, keep).
finding_disposition(f19, accepted).
finding_disposition(f20, keep).
finding_disposition(f21, accepted).
finding_disposition(f22, accepted).
finding_disposition(f23, keep).
finding_disposition(f24, keep).
finding_disposition(f25, keep).

disposition_reason(f01, 'prevents_phantom_state_advance_at_seconds_per_run_cost').
disposition_reason(f02, 'unenforced_permission_bits_are_negative_value_safety').
disposition_reason(f03, 'per_import_gate_rerun_revalidates_an_already_validated_corpus').
disposition_reason(f04, 'two_ledgers_record_one_fact').
disposition_reason(f05, 'prevents_the_hand_edit_corruption_the_history_actually_shows').
disposition_reason(f06, 'one_off_generators_erode_the_mandated_write_path_by_existing').
disposition_reason(f07, 'identical_shims_are_pure_drift_surface').
disposition_reason(f08, 'tool_self_description_contradicts_declared_authority').
disposition_reason(f09, 'migration_text_stranded_on_a_retired_line').
disposition_reason(f10, 'general_norm_overfit_with_one_subject_statute').
disposition_reason(f11, 'pinned_dependency_path_becomes_the_outage').
disposition_reason(f12, 'person_materialization_closes_the_embedded_scalar_graph_hole').
disposition_reason(f13, 'prevents_strings_instead_of_nodes_corpus_rot').
disposition_reason(f14, 'prose_and_checker_disagree_on_third_states').
disposition_reason(f15, 'silent_empty_frontier_feeds_a_false_stop_condition').
disposition_reason(f16, 'prose_ban_where_code_enforces_totally').
disposition_reason(f17, 'best_designed_machinery_in_the_system_keep_and_extend_its_reach').
disposition_reason(f18, 'visibility_over_hiding_is_conservative_correct').
disposition_reason(f19, 'ceremony_above_reuse_value_discourages_writing_facts_down').
disposition_reason(f20, 'contract_changes_need_human_sign_off_keep_scoped_do_not_export').
disposition_reason(f21, 'policy_unenforceable_in_its_target_runtime').
disposition_reason(f22, 'contract_names_fewer_writers_than_disk_ships').
disposition_reason(f23, 'prevents_the_hardest_retro_repair_class_dangling_graphs').
disposition_reason(f24, 'typo_is_now_a_generated_contract_renaming_breaks_consumers').
disposition_reason(f25, 'cheap_useful_continuation_state_reality_matches_policy').

open_question(person_observation_container_representation).
open_question(evidence_ledger_ownership_repo_vs_global_policy).
open_question(canonical_root_registry_format_and_checker).
open_question(third_control_states_vocabulary_draining_finishing).

finding_execution(P, deferred_to_owner_approval) :-
    proposal(P, _).
