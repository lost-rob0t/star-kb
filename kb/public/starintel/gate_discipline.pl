:- module(starintel_gate_discipline,
          [ work_authorized/1,
            work_blocked/1,
            fail_closed_condition/1,
            pause_effect/1,
            authoritative_semantics/1,
            validation_outcome_recorded/2,
            blocking_validation_outcome/1,
            evidence_head/2,
            current_head/1,
            gate_command_ran/1,
            evidence_exact_head/1,
            stale_evidence/1,
            merge_permitted/1,
            merge_decision/2,
            on_validation_failure/1,
            prohibition/1,
            norm/2,
            gate_cadence/1,
            gate_boundary/1,
            recommended_gate_point/1,
            redundant_gate_point/1,
            redundance_reason/2
          ]).

:- dynamic validation_outcome_recorded/2.
:- dynamic evidence_head/2.
:- dynamic current_head/1.
:- dynamic gate_command_ran/1.

work_authorized(control(Enabled, State)) :-
    Enabled == enabled,
    State == running.

work_blocked(Control) :-
    \+ work_authorized(Control).

fail_closed_condition(unreadable_control_file).
fail_closed_condition(invalid_control_file).
fail_closed_condition(control_plane_disabled).
fail_closed_condition(control_state_not_running).

pause_effect(preserve_existing_worktrees_branches_artifacts_and_failure_evidence).
pause_effect(running_validation_may_finish_without_new_authorization).
pause_effect(no_queue_coverage_or_actor_state_advance).
pause_effect(resume_only_on_explicit_operator_instruction).

authoritative_semantics(fail_closed_checker_over_prose).

blocking_validation_outcome(failing).
blocking_validation_outcome(skipped).
blocking_validation_outcome(unavailable).
blocking_validation_outcome(inconclusive).

evidence_exact_head(Ctx) :-
    evidence_head(Ctx, Head),
    current_head(Head).

stale_evidence(Ctx) :-
    evidence_head(Ctx, Head),
    current_head(Current),
    Head \= Current.

merge_permitted(Ctx) :-
    validation_outcome_recorded(Ctx, passing),
    evidence_exact_head(Ctx),
    gate_command_ran(Ctx).

merge_decision(Ctx, blocked) :-
    \+ merge_permitted(Ctx).

on_validation_failure(leave_change_in_draft_state).
on_validation_failure(identify_exact_invalid_record_or_invariant).
on_validation_failure(fix_or_remove_invalid_change).
on_validation_failure(rerun_complete_gate).
on_validation_failure(merge_only_after_local_gate_and_required_checks_pass).

prohibition(never_merge_invalid_documents).
prohibition(no_merge_with_promise_to_repair_later).
prohibition(no_validator_bypass).
prohibition(no_schema_weakening_to_pass_a_check).
prohibition(no_hiding_invalid_values_in_extensions).

norm(gate_discipline, fail_closed_control_plane).
norm(gate_discipline, single_canonical_gate_command).
norm(gate_discipline, single_evidence_ledger).
norm(gate_discipline, exact_head_evidence).
norm(gate_discipline, never_merge_invalid).
norm(gate_discipline, fail_closed_semantics_outrank_prose).

gate_cadence(gate_at_boundaries_not_steps).

gate_boundary(pass_end).
gate_boundary(integration_merge).

recommended_gate_point(pass_end).
recommended_gate_point(integration_merge).

redundant_gate_point(single_import).

redundance_reason(single_import,
                  writer_side_full_corpus_validation_already_covers_intra_pass_drift).
