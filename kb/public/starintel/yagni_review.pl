:- module(starintel_yagni_review,
          [ review_dimension/1,
            review_question/2,
            rule_profile/3,
            level/2,
            ceremonial_reason/1,
            ceremonial_candidate/1,
            load_bearing/1,
            looks_redundant/1,
            deletion_trap/1,
            safe_delete/1,
            unenforced_safety_claim/1,
            verdict/1,
            verdict_rule/2,
            same_product/2,
            consolidation_candidate/2,
            consolidation_invariant/1,
            enforcement_gap/1,
            prefer_enforcement_over_prose/1,
            ceremony_budget/1,
            provenance_core_fields/1
          ]).

:- dynamic rule_profile/3.
:- dynamic same_product/2.

review_dimension(cost_benefit).
review_dimension(load_bearing_vs_ceremonial).
review_dimension(enforced_vs_prose).
review_dimension(duplication).
review_dimension(drift_surface).
review_dimension(deletion_trap).
review_dimension(unenforced_permission).

review_question(cost_benefit,
                'recurring cost imposed per run versus likelihood the rule is wrong').
review_question(load_bearing_vs_ceremonial,
                'which corruption or waste mode does the rule actually prevent').
review_question(enforced_vs_prose,
                'is a cheaper total mechanism available than exhortation').
review_question(duplication,
                'do two rules or tools record the same fact').
review_question(drift_surface,
                'can duplicated text or literals drift from the authority').
review_question(deletion_trap,
                'looks redundant but is load-bearing for another consumer').
review_question(unenforced_permission,
                'does the rule promise enforcement that nothing implements').

level(low, 1).
level(medium, 2).
level(high, 3).

ceremonial_candidate(Rule) :-
    rule_profile(Rule, cost, Cost),
    level(Cost, Rank),
    Rank >= 2,
    ceremonial_reason(Rule).

ceremonial_reason(Rule) :-
    rule_profile(Rule, failure_prevented, none).
ceremonial_reason(Rule) :-
    unenforced_safety_claim(Rule).

load_bearing(Rule) :-
    rule_profile(Rule, failure_prevented, Failure),
    Failure \= none.

looks_redundant(Rule) :-
    rule_profile(Rule, looks_redundant, true).

deletion_trap(Rule) :-
    looks_redundant(Rule),
    load_bearing(Rule).

safe_delete(Rule) :-
    looks_redundant(Rule),
    \+ load_bearing(Rule),
    \+ rule_profile(Rule, referenced_by, _).

unenforced_safety_claim(Rule) :-
    rule_profile(Rule, declares_permission, true),
    \+ rule_profile(Rule, enforces_permission, true).

verdict(delete_or_enforce) :-
    unenforced_safety_claim(_).
verdict(consolidate_duplicates) :-
    consolidation_candidate(_, _).
verdict(keep_load_bearing) :-
    load_bearing(_).

verdict_rule(Rule, delete_or_enforce) :-
    unenforced_safety_claim(Rule).
verdict_rule(Rule, consolidate) :-
    consolidation_candidate(Rule, _).
verdict_rule(Rule, keep) :-
    load_bearing(Rule),
    \+ ceremonial_reason(Rule).

consolidation_candidate(A, B) :-
    same_product(A, B).

consolidation_invariant(keep_at_least_one_instance).

enforcement_gap(Rule) :-
    rule_profile(Rule, ban_medium, prose),
    rule_profile(Rule, cheap_total_enforcement, true).

prefer_enforcement_over_prose(Rule) :-
    enforcement_gap(Rule).

ceremony_budget(write_cost_must_not_exceed_expected_reuse_value).

provenance_core_fields([id, subject, value, author, source, supersedes]).
