:- module(star_reasoning,
          [ graph_edge/5,
            path/4,
            tool_document/2,
            tool_neighbors/3,
            tool_path/4,
            tool_explain_relation/2,
            tool_timeline/2,
            tool_contradictions/2,
            tool_compare/3,
            tool_sources/2,
            tool_why_not/4,
            tool_route_reasoning/6
          ]).

:- use_module(star_json).

graph_edge(Source, Predicate, Target, relation(RelationId), out) :-
    star_relation(RelationId, Source, Predicate, Target, _Directed, false, _Confidence, _Start, _End).
graph_edge(Target, Predicate, Source, relation(RelationId), in) :-
    star_relation(RelationId, Source, Predicate, Target, _Directed, false, _Confidence, _Start, _End).
graph_edge(Source, references(Path), Target, reference(Source, Path), out) :-
    star_ref(Source, Path, Target).
graph_edge(Target, referenced_by(Path), Source, reference(Source, Path), in) :-
    star_ref(Source, Path, Target).

path(Source, Target, MaxDepth, Path) :-
    integer(MaxDepth), MaxDepth >= 1,
    path_(Source, Target, MaxDepth, [Source], Path).

path_(Target, Target, _Depth, Visited, Path) :-
    reverse(Visited, Path).
path_(Current, Target, Depth, Visited, Path) :-
    Depth > 0,
    graph_edge(Current, _Predicate, Next, _Evidence, out),
    \+ memberchk(Next, Visited),
    NextDepth is Depth - 1,
    path_(Next, Target, NextDepth, [Next|Visited], Path).

tool_document(Id, document(Id, DType, Dataset, Schema, Version, Hash, Profile)) :-
    star_doc(Id, DType, Dataset, Schema, Version, Hash),
    star_profile(Id, ProfileName, ProfileVersion, Revision, Release),
    Profile = profile(ProfileName, ProfileVersion, Revision, Release).

tool_neighbors(Id, Direction, edge(Id, Predicate, Other, Evidence, EdgeDirection)) :-
    memberchk(Direction, [out, both]),
    graph_edge(Id, Predicate, Other, Evidence, EdgeDirection).
tool_neighbors(Id, Direction, edge(Other, Predicate, Id, Evidence, EdgeDirection)) :-
    memberchk(Direction, [in, both]),
    graph_edge(Id, Predicate, Other, Evidence, EdgeDirection).

tool_path(Source, Target, MaxDepth, path(Path)) :-
    path(Source, Target, MaxDepth, Path).

tool_explain_relation(RelationId,
                      relation(RelationId, Subject, Predicate, Object,
                               directed(Directed), negated(Negated), confidence(Confidence),
                               interval(Start, End), sources(Sources), evidence(Evidence),
                               provenance(Provenance), qualifiers(Qualifiers))) :-
    star_relation(RelationId, Subject, Predicate, Object, Directed, Negated, Confidence, Start, End),
    findall(source(SourceId, Kind, Locator, Credibility, Reliability, Hash),
            star_source(RelationId, SourceId, Kind, Locator, Credibility, Reliability, Hash),
            Sources),
    findall(evidence(EvidenceId, SourceId, Role, Claim, EConfidence, Status),
            star_evidence(RelationId, EvidenceId, SourceId, Role, Claim, EConfidence, Status),
            Evidence),
    findall(provenance(Collector, Actor, Tool, Model, RunId, Method, ImportedFrom, Transform),
            star_provenance(RelationId, Collector, Actor, Tool, Model, RunId, Method, ImportedFrom, Transform),
            Provenance),
    findall(qualifier(Key, Value), star_relation_qualifier(RelationId, Key, Value), Qualifiers).

tool_timeline(Id, time(DocumentId, Key, Value, Path)) :-
    ( DocumentId = Id ; graph_edge(Id, _Predicate, DocumentId, _Evidence, out) ),
    star_time(DocumentId, Key, Value, Path).

tool_contradictions(Id, relation_conflict(PositiveId, NegativeId, Subject, Predicate, Object)) :-
    star_relation(PositiveId, Subject, Predicate, Object, _D1, false, _C1, _S1, _E1),
    star_relation(NegativeId, Subject, Predicate, Object, _D2, true, _C2, _S2, _E2),
    (Subject = Id ; Object = Id).
tool_contradictions(Id, evidence_conflict(DocumentId, EvidenceId, ContradictedEvidenceId)) :-
    (DocumentId = Id ; graph_edge(Id, _Predicate, DocumentId, _Evidence, out)),
    star_evidence_contradicts(DocumentId, EvidenceId, ContradictedEvidenceId).

tool_compare(Left, Right, shared_predicate(Predicate, LeftObject, RightObject)) :-
    star_relation(_LRel, Left, Predicate, LeftObject, _LD, false, _LC, _LS, _LE),
    star_relation(_RRel, Right, Predicate, RightObject, _RD, false, _RC, _RS, _RE).
tool_compare(Left, Right, shared_reference(Target)) :-
    star_ref(Left, _LeftPath, Target),
    star_ref(Right, _RightPath, Target).

tool_sources(Id, source(SourceId, Kind, Locator, Credibility, Reliability, Hash)) :-
    star_source(Id, SourceId, Kind, Locator, Credibility, Reliability, Hash).
tool_sources(Id, provenance(Collector, Actor, Tool, Model, RunId, Method, ImportedFrom, Transform)) :-
    star_provenance(Id, Collector, Actor, Tool, Model, RunId, Method, ImportedFrom, Transform).

tool_why_not(Subject, Predicate, Object, already_supported(RelationId)) :-
    star_relation(RelationId, Subject, Predicate, Object, _Directed, false, _Confidence, _Start, _End), !.
tool_why_not(Subject, Predicate, Object, explicitly_negated(RelationId)) :-
    star_relation(RelationId, Subject, Predicate, Object, _Directed, true, _Confidence, _Start, _End), !.
tool_why_not(Subject, Predicate, Object, missing_direct_relation(Subject, Predicate, Object)).

% Capability routing mirrors STAR-AUTO-RESEARCH-001: callers ask for semantics,
% not an engine. The runtime binds capabilities to SWI, ProbLog, XSB, etc.
tool_route_reasoning(_Task, true, true, _Explain, _Bulk, recursive_probabilistic_query).
tool_route_reasoning(_Task, true, false, _Explain, _Bulk, probabilistic_query).
tool_route_reasoning(_Task, false, true, true, false, answer_set_or_tabled_explanation).
tool_route_reasoning(_Task, false, true, false, false, recursive_tabled_query).
tool_route_reasoning(_Task, false, _Recursive, _Explain, true, bulk_datalog_closure).
tool_route_reasoning(_Task, false, false, true, false, deterministic_explanation).
tool_route_reasoning(_Task, false, false, false, false, deterministic_rule_evaluation).
