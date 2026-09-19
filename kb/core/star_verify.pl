:- module(star_verify,
          [ verify_candidate/2,
            verification_issue/2,
            vote_tally/5,
            print_verification_report/1
          ]).

:- use_module(library(http/json)).

:- discontiguous verification_issue/2.

:- multifile verification_document/12.
:- multifile verification_policy/12.
:- multifile verification_source/2.
:- multifile verification_evidence/4.
:- multifile verification_vote/7.

:- dynamic verification_document/12.
:- dynamic verification_policy/12.
:- dynamic verification_source/2.
:- dynamic verification_evidence/4.
:- dynamic verification_vote/7.

valid_status(candidate).
valid_status(generated).
valid_stance(approve).
valid_stance(reject).
valid_stance(abstain).

non_empty_atom(Value) :-
    atom(Value),
    atom_length(Value, Length),
    Length > 0.

hex_code(Code) :-
    code_type(Code, xdigit(_)).

valid_sha256(Value) :-
    atom(Value),
    atom_length(Value, 71),
    sub_atom(Value, 0, 7, 64, 'sha256:'),
    sub_atom(Value, 7, 64, 0, Hex),
    atom_codes(Hex, Codes),
    maplist(hex_code, Codes).

verification_issue(Id, missing_document) :-
    \+ verification_document(Id, _, _, _, _, _, _, _, _, _, _, _).

verification_issue(Id, missing_policy) :-
    verification_document(Id, _, _, _, _, _, _, _, _, _, _, _),
    \+ verification_policy(Id, _, _, _, _, _, _, _, _, _, _, _).

verification_issue(Id, invalid_document_identity) :-
    verification_document(Id, DType, Dataset, Schema, Version, _Actor, _RunId, _Method,
                          _SpecId, _SpecVersion, _SpecDigest, _Status),
    ( \+ non_empty_atom(DType)
    ; \+ non_empty_atom(Dataset)
    ; \+ non_empty_atom(Schema)
    ; \+ integer(Version)
    ; Version < 0
    ).

verification_issue(Id, missing_provenance) :-
    verification_document(Id, _DType, _Dataset, _Schema, _Version, Actor, RunId, Method,
                          _SpecId, _SpecVersion, _SpecDigest, _Status),
    ( \+ non_empty_atom(Actor)
    ; \+ non_empty_atom(RunId)
    ; \+ non_empty_atom(Method)
    ).

verification_issue(Id, invalid_knowledge_status(Status)) :-
    verification_document(Id, _, _, _, _, _, _, _, _, _, _, Status),
    \+ valid_status(Status).

verification_issue(Id, schema_mismatch(Actual, Required)) :-
    verification_document(Id, _, _, Actual, _, _, _, _, _, _, _, _),
    verification_policy(Id, _, _, _, Required, _, _, _, _, _, _, _),
    Actual \= Required.

verification_issue(Id, spec_mismatch(ActualId, ActualVersion, RequiredId, RequiredVersion)) :-
    verification_document(Id, _, _, _, _, _, _, _, ActualId, ActualVersion, _ActualDigest, _),
    verification_policy(Id, RequiredId, RequiredVersion, _RequiredDigest, _, _, _, _, _, _, _, _),
    (ActualId \= RequiredId ; ActualVersion \= RequiredVersion).

verification_issue(Id, invalid_spec_digest(ActualDigest)) :-
    verification_document(Id, _, _, _, _, _, _, _, _, _, ActualDigest, _),
    \+ valid_sha256(ActualDigest).

verification_issue(Id, spec_digest_mismatch(ActualDigest, RequiredDigest)) :-
    verification_document(Id, _, _, _, _, _, _, _, _, _, ActualDigest, _),
    verification_policy(Id, _, _, RequiredDigest, _, _, _, _, _, _, _, _),
    ActualDigest \= RequiredDigest.

verification_issue(Id, verifier_mismatch(Actual)) :-
    verification_policy(Id, _, _, _, _, _, _, _, _, _, _, Actual),
    Actual \= 'starintel-verify-v1'.

verification_issue(Id, insufficient_sources(Count, Minimum)) :-
    verification_policy(Id, _, _, _, _, _, _, _, Minimum, _, _, _),
    findall(SourceId, verification_source(Id, SourceId), Sources),
    sort(Sources, Unique),
    length(Unique, Count),
    Count < Minimum.

verification_issue(Id, insufficient_evidence(Count, Minimum)) :-
    verification_policy(Id, _, _, _, _, _, _, _, _, Minimum, _, _),
    findall(EvidenceId, verification_evidence(Id, EvidenceId, _, _), Evidence),
    sort(Evidence, Unique),
    length(Unique, Count),
    Count < Minimum.

verification_issue(Id, evidence_missing_source(EvidenceId)) :-
    verification_evidence(Id, EvidenceId, SourceId, _Status),
    \+ non_empty_atom(SourceId).

verification_issue(Id, evidence_unknown_source(EvidenceId, SourceId)) :-
    verification_evidence(Id, EvidenceId, SourceId, _Status),
    non_empty_atom(SourceId),
    \+ verification_source(Id, SourceId).

verification_issue(Id, duplicate_source_id(SourceId)) :-
    verification_source(Id, SourceId),
    findall(1, verification_source(Id, SourceId), Matches),
    length(Matches, Count),
    Count > 1.

verification_issue(Id, duplicate_evidence_id(EvidenceId)) :-
    verification_evidence(Id, EvidenceId, _, _),
    findall(1, verification_evidence(Id, EvidenceId, _, _), Matches),
    length(Matches, Count),
    Count > 1.

verification_issue(Id, vote_spec_mismatch(Voter, VoteSpecId, VoteSpecVersion)) :-
    verification_policy(Id, RequiredId, RequiredVersion, _RequiredDigest, _, _, _, _, _, _, _, _),
    verification_vote(Id, Voter, _Stance, _Weight, VoteSpecId, VoteSpecVersion, _VoteSpecDigest),
    (VoteSpecId \= RequiredId ; VoteSpecVersion \= RequiredVersion).

verification_issue(Id, vote_spec_digest_mismatch(Voter, VoteSpecDigest, RequiredDigest)) :-
    verification_policy(Id, _, _, RequiredDigest, _, _, _, _, _, _, _, _),
    verification_vote(Id, Voter, _Stance, _Weight, _VoteSpecId, _VoteSpecVersion, VoteSpecDigest),
    VoteSpecDigest \= RequiredDigest.

verification_issue(Id, invalid_vote_spec_digest(Voter, VoteSpecDigest)) :-
    verification_vote(Id, Voter, _Stance, _Weight, _VoteSpecId, _VoteSpecVersion, VoteSpecDigest),
    \+ valid_sha256(VoteSpecDigest).

verification_issue(Id, invalid_vote(Voter, Stance, Weight)) :-
    verification_vote(Id, Voter, Stance, Weight, _SpecId, _SpecVersion, _SpecDigest),
    ( \+ non_empty_atom(Voter)
    ; \+ valid_stance(Stance)
    ; \+ integer(Weight)
    ; Weight < 1
    ; Weight > 10000
    ).

verification_issue(Id, self_vote(Voter)) :-
    verification_policy(Id, _, _, _, _, _, _, _, _, _, false, _),
    verification_document(Id, _, _, _, _, Voter, _, _, _, _, _, _),
    verification_vote(Id, Voter, _Stance, _Weight, _SpecId, _SpecVersion, _SpecDigest).

verification_issue(Id, duplicate_voter(Voter)) :-
    verification_vote(Id, Voter, _, _, _, _, _),
    findall(1, verification_vote(Id, Voter, _, _, _, _, _), Votes),
    length(Votes, Count),
    Count > 1.

sum_weights([], 0).
sum_weights([Weight|Rest], Total) :-
    sum_weights(Rest, Tail),
    Total is Weight + Tail.

stance_weight(Id, Stance, Total) :-
    findall(Weight, verification_vote(Id, _Voter, Stance, Weight, _SpecId, _SpecVersion, _SpecDigest), Weights),
    sum_weights(Weights, Total).

vote_tally(Id, Approve, Reject, Abstain, Total) :-
    stance_weight(Id, approve, Approve),
    stance_weight(Id, reject, Reject),
    stance_weight(Id, abstain, Abstain),
    Total is Approve + Reject + Abstain.

approval_count(Id, Count) :-
    findall(Voter, verification_vote(Id, Voter, approve, _Weight, _SpecId, _SpecVersion, _SpecDigest), Voters),
    length(Voters, Count).

total_vote_count(Id, Count) :-
    findall(Voter, verification_vote(Id, Voter, _Stance, _Weight, _SpecId, _SpecVersion, _SpecDigest), Voters),
    length(Voters, Count).

verification_issue(Id, insufficient_approvals(Count, Minimum)) :-
    verification_policy(Id, _, _, _, _, Minimum, _, _, _, _, _, _),
    approval_count(Id, Count),
    Count < Minimum.

verification_issue(Id, insufficient_votes(Count, Minimum)) :-
    verification_policy(Id, _, _, _, _, _, Minimum, _, _, _, _, _),
    total_vote_count(Id, Count),
    Count < Minimum.

verification_issue(Id, approval_ratio_below(Approve, Total, Numerator, Denominator)) :-
    verification_policy(Id, _, _, _, _, _, _, ratio(Numerator, Denominator), _, _, _, _),
    vote_tally(Id, Approve, _Reject, _Abstain, Total),
    ( Total =:= 0
    ; Approve * Denominator < Total * Numerator
    ).

verify_candidate(Id, verified) :-
    \+ verification_issue(Id, _), !.
verify_candidate(Id, rejected(Issues)) :-
    findall(Issue, verification_issue(Id, Issue), Raw),
    sort(Raw, Issues).

issue_string(Issue, String) :-
    term_string(Issue, String, [quoted(true)]).

print_verification_report(Id) :-
    verify_candidate(Id, DecisionTerm),
    ( DecisionTerm = verified -> Decision = verified ; Decision = rejected ),
    findall(Issue, verification_issue(Id, Issue), RawIssues),
    sort(RawIssues, Issues),
    maplist(issue_string, Issues, IssueStrings),
    vote_tally(Id, Approve, Reject, Abstain, Total),
    approval_count(Id, ApprovalCount),
    total_vote_count(Id, VoteCount),
    Report = _{candidateId:Id,
               decision:Decision,
               issues:IssueStrings,
               approveWeight:Approve,
               rejectWeight:Reject,
               abstainWeight:Abstain,
               totalWeight:Total,
               approvalCount:ApprovalCount,
               voteCount:VoteCount},
    json_write_dict(current_output, Report),
    nl.
