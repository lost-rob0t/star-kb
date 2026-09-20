from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "kb" / "public" / "starintel"
SWIPL = shutil.which("swipl")

MODULES = [
    "task_lifecycle.pl",
    "write_path.pl",
    "identity_safety.pl",
    "provenance.pl",
    "gate_discipline.pl",
    "yagni_review.pl",
    "iq_improvements.pl",
]


def run_goal(goal: str, modules: list[str], loader: bool = False) -> subprocess.CompletedProcess:
    command = [SWIPL, "-q"]
    if loader:
        sources = [KB_DIR / "starintel_public.pl"]
    else:
        sources = [KB_DIR / name for name in modules]
    command += ["-s", *[str(path) for path in sources]]
    command += ["-g", f"(({goal}) -> halt(0) ; halt(1))", "-t", "halt(1)"]
    return subprocess.run(command, capture_output=True, text=True, timeout=60, cwd=ROOT)


def assert_prolog(test: unittest.TestCase, goal: str, modules: list[str], loader: bool = False) -> None:
    result = run_goal(goal, modules, loader=loader)
    test.assertEqual(
        result.returncode,
        0,
        f"goal failed:\n{goal}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )
    test.assertNotIn("ERROR", result.stderr, result.stderr)
    test.assertNotIn("Warning", result.stderr, result.stderr)


@unittest.skipUnless(SWIPL and KB_DIR.is_dir(), "swipl or public StarIntel KB not available")
class PublicStarIntelKbTests(unittest.TestCase):
    def test_every_module_consults_cleanly(self) -> None:
        for name in MODULES + ["starintel_public.pl"]:
            result = subprocess.run(
                [SWIPL, "-q", "-s", str(KB_DIR / name), "-g", "halt", "-t", "halt(1)"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, f"{name}: {result.stderr}")
            self.assertEqual(result.stderr, "", f"{name} produced load output: {result.stderr}")

    def test_email_task_completeness_rule(self) -> None:
        goal = "\n".join([
            "M = starintel_task_lifecycle,",
            "assertz(M:task_artifact(t1, email_artifact)),",
            "forall(member(R, [canonical_surface_updated, imported_through_canonical_path,",
            "                source_document, typed_record(email_message), person_records(sender),",
            "                person_records(recipients), person_records(explicit_body_names),",
            "                relation_records(linking_participants_to_sources_and_persons)]),",
            "       assertz(M:provided(t1, R))),",
            "assertz(M:task_artifact(t2, email_artifact)),",
            "M:task_complete(t1),",
            "\\+ M:task_complete(t2),",
            "M:missing_requirement(t2, person_records(recipients)),",
            "M:insufficient_evidence(email_artifact, image_only),",
            "M:insufficient_evidence(social_artifact, embedded_scalar_authors_without_entities)",
        ])
        assert_prolog(self, goal, ["task_lifecycle.pl"])

    def test_write_path_storage_and_versioning(self) -> None:
        goal = "\n".join([
            "W = starintel_write_path,",
            "W:storage_path(db, person, 'starintel:person:ada', 'db/person/starintel:person:ada.ndjson'),",
            "\\+ W:id_path_safe('a/b'),",
            "\\+ W:id_path_safe(''),",
            "W:id_path_safe('starintel:person:ada'),",
            "W:change_decision(same_id, 1, 2, intentional_replacement),",
            "W:change_decision(same_id, 2, 2, documented_correction),",
            "W:change_decision(different_id, 1, 1, new_record),",
            "W:prohibited_write_method(heredoc),",
            "W:sanctioned_write(single_record, transactional_writer),",
            "assertz(W:resolves_to_normalized_record(e1)),",
            "W:endpoint_ok(e1),",
            "assertz(W:schema_unresolved_representation(e2)),",
            "W:endpoint_ok(e2),",
            "W:dangling_endpoint(e3)",
        ])
        assert_prolog(self, goal, ["write_path.pl"])

    def test_ambiguous_identity_merge_rejected(self) -> None:
        goal = "\n".join([
            "I = starintel_identity_safety,",
            "assertz(I:ambiguous_candidate(a, b)),",
            "assertz(I:identity_confirmed(a, c, evidence_direct)),",
            "I:merge_forbidden(a, b),",
            "I:merge_permitted(a, c),",
            "I:person_record_forbidden(guess_legal_identity),",
            "I:candidate_link_requirement(no_force_merge),",
            "I:entity_creation_asserts_real_world_identity(false)",
        ])
        assert_prolog(self, goal, ["identity_safety.pl"])

    def test_stable_identifier_resolves_to_single_entity(self) -> None:
        goal = "\n".join([
            "I = starintel_identity_safety,",
            "assertz(I:stable_identifier(src1, handle_x, e1)),",
            "setof(E, I:entity_for_observation(src1, handle_x, E), [e1]),",
            "findall(D, I:observation_divergence(src1, handle_x, _, D), [])",
        ])
        assert_prolog(self, goal, ["identity_safety.pl"])

    def test_claims_vs_corroborated_facts(self) -> None:
        goal = "\n".join([
            "P = starintel_provenance,",
            "assertz(P:claim_source(c1, s1, independent)),",
            "assertz(P:claim_source(c2, s1, independent)),",
            "assertz(P:claim_source(c2, s2, independent)),",
            "P:claim_status(c1, attributed_claim),",
            "P:claim_status(c2, corroborated_fact),",
            "P:empty_source_policy(visible_in_unverified_ledger)",
        ])
        assert_prolog(self, goal, ["provenance.pl"])

    def test_provenance_fields_required(self) -> None:
        goal = "\n".join([
            "P = starintel_provenance,",
            "assertz(P:document_field(d1, sources)),",
            "assertz(P:document_field(d1, evidence)),",
            "assertz(P:document_field(d1, uncertainty)),",
            "P:provenance_violation(d1, missing_field(lineage)),",
            "\\+ P:provenance_complete(d1),",
            "assertz(P:document_field(d1, lineage)),",
            "P:provenance_complete(d1)",
        ])
        assert_prolog(self, goal, ["provenance.pl"])

    def test_control_plane_fails_closed(self) -> None:
        goal = "\n".join([
            "G = starintel_gate_discipline,",
            "G:work_authorized(control(enabled, running)),",
            "forall(member(S, [paused, draining, finishing, disabled]),",
            "       G:work_blocked(control(enabled, S))),",
            "G:work_blocked(control(disabled, running)),",
            "G:fail_closed_condition(unreadable_control_file)",
        ])
        assert_prolog(self, goal, ["gate_discipline.pl"])

    def test_merge_gate_required_for_passing_case(self) -> None:
        goal = "\n".join([
            "G = starintel_gate_discipline,",
            "assertz(G:validation_outcome_recorded(pr_ok, passing)),",
            "assertz(G:evidence_head(pr_ok, h1)),",
            "assertz(G:current_head(h1)),",
            "assertz(G:gate_command_ran(pr_ok)),",
            "G:merge_permitted(pr_ok)",
        ])
        assert_prolog(self, goal, ["gate_discipline.pl"])

    def test_merge_blocked_on_stale_or_skipped_evidence(self) -> None:
        goal = "\n".join([
            "G = starintel_gate_discipline,",
            "assertz(G:current_head(h1)),",
            "assertz(G:validation_outcome_recorded(pr_stale, passing)),",
            "assertz(G:evidence_head(pr_stale, h0)),",
            "assertz(G:gate_command_ran(pr_stale)),",
            "G:stale_evidence(pr_stale),",
            "G:merge_decision(pr_stale, blocked),",
            "assertz(G:validation_outcome_recorded(pr_skip, skipped)),",
            "assertz(G:evidence_head(pr_skip, h1)),",
            "assertz(G:gate_command_ran(pr_skip)),",
            "G:merge_decision(pr_skip, blocked)",
        ])
        assert_prolog(self, goal, ["gate_discipline.pl"])

    def test_gate_cadence_policy(self) -> None:
        goal = "\n".join([
            "G = starintel_gate_discipline,",
            "setof(B, G:recommended_gate_point(B), [integration_merge, pass_end]),",
            "\\+ G:recommended_gate_point(single_import),",
            "G:redundant_gate_point(single_import),",
            "G:redundance_reason(single_import, writer_side_full_corpus_validation_already_covers_intra_pass_drift),",
            "G:norm(gate_discipline, single_canonical_gate_command),",
            "G:norm(gate_discipline, single_evidence_ledger),",
            "G:gate_cadence(gate_at_boundaries_not_steps)",
        ])
        assert_prolog(self, goal, ["gate_discipline.pl"])

    def test_yagni_checklist_ranks_ceremonial_rule(self) -> None:
        goal = "\n".join([
            "Y = starintel_yagni_review,",
            "assertz(Y:rule_profile(per_import_gate_rerun, cost, high)),",
            "assertz(Y:rule_profile(per_import_gate_rerun, failure_prevented, none)),",
            "assertz(Y:rule_profile(control_plane_gate, cost, low)),",
            "assertz(Y:rule_profile(control_plane_gate, failure_prevented, phantom_state_advance)),",
            "Y:ceremonial_candidate(per_import_gate_rerun),",
            "\\+ Y:ceremonial_candidate(control_plane_gate),",
            "Y:verdict_rule(control_plane_gate, keep)",
        ])
        assert_prolog(self, goal, ["yagni_review.pl"])

    def test_yagni_deletion_traps_and_unenforced_claims(self) -> None:
        goal = "\n".join([
            "Y = starintel_yagni_review,",
            "assertz(Y:rule_profile(allow_permission_bits, declares_permission, true)),",
            "assertz(Y:rule_profile(allow_permission_bits, cost, medium)),",
            "assertz(Y:rule_profile(allow_permission_bits, failure_prevented, none)),",
            "Y:unenforced_safety_claim(allow_permission_bits),",
            "Y:verdict_rule(allow_permission_bits, delete_or_enforce),",
            "assertz(Y:rule_profile(unverified_ledger, looks_redundant, true)),",
            "assertz(Y:rule_profile(unverified_ledger, failure_prevented, breaking_ledger_consumers)),",
            "Y:deletion_trap(unverified_ledger),",
            "\\+ Y:safe_delete(unverified_ledger)",
        ])
        assert_prolog(self, goal, ["yagni_review.pl"])

    def test_proposals_stay_proposed_with_rationale(self) -> None:
        goal = "\n".join([
            "I = starintel_iq_improvements,",
            "forall(I:proposal(P, _), (I:proposal_status(P, proposed),",
            "                       I:proposal_rationale(P, _),",
            "                       I:proposal_effect(P, _))),",
            "\\+ I:proposal_status(_, approved),",
            "forall(I:finding_disposition(F, _), atom(F))",
        ])
        assert_prolog(self, goal, ["iq_improvements.pl"])

    def test_all_25_findings_have_dispositions(self) -> None:
        expected = {f"f{n:02d}" for n in range(1, 26)}
        result = run_goal(
            "findall(F, starintel_iq_improvements:finding_disposition(F, _), Fs), "
            "sort(Fs, Sorted), length(Sorted, 25)",
            ["iq_improvements.pl"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        listed = run_goal(
            "forall(starintel_iq_improvements:finding_disposition(F, _), format('~w~n', [F]))",
            ["iq_improvements.pl"],
        )
        self.assertEqual(expected, {line for line in listed.stdout.splitlines() if line})

    def test_loader_reexports_all_modules(self) -> None:
        goal = "\n".join([
            "starintel_public:task_requirement(canonical_surface_updated),",
            "starintel_public:sanctioned_write(record_batch, validated_batch_importer),",
            "starintel_public:merge_forbidden(x, y),",
            "starintel_public:claim_status(c, attributed_claim),",
            "starintel_public:gate_boundary(pass_end),",
            "starintel_public:review_dimension(cost_benefit),",
            "starintel_public:iq_principle(one_ledger_per_fact)",
        ])
        assert_prolog(self, goal, [], loader=True)


if __name__ == "__main__":
    unittest.main()
