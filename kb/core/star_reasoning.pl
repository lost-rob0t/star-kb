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
            tool_route_reasoning/6,
            tool_values/3,
            tool_referrers/2,
            tool_packet/3
          ]).

:- use_module(star_json).

% Graph edges preserve whether they came from an explicit relation or a generic
% StarIntel reference. Relation edges carry the relation document as evidence.
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
    graph_edge(Current, _Predicate, Next, _Evidence, _Direction),
    \+ memberchk(Next, Visited),
    NextDepth is Depth - 1,
    path_(Next, Target, NextDepth, [Next|Visited], Path).

tool_document(Id, document(Id, DType, Dataset, Schema, Version, Hash, Profile)) :-
    star_doc(Id, DType, Dataset, Schema, Version, Hash),
    star_profile(Id, ProfileName, ProfileVersion, Revision, Release),
    Profile = profile(ProfileName, ProfileVersion, Revision, Release).

tool_neighbors(Id, Direction, edge(Id, Predicate, Other, Evidence, out)) :-
    memberchk(Direction, [out, both]),
    graph_edge(Id, Predicate, Other, Evidence, out).
tool_neighbors(Id, Direction, edge(Other, Predicate, Id, Evidence, in)) :-
    memberchk(Direction, [in, both]),
    graph_edge(Id, Predicate, Other, Evidence, in).

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

related_document(Id, Id).
related_document(Id, DocumentId) :- star_relation(DocumentId, Id, _Predicate, _Object, _D, _N, _C, _S, _E).
related_document(Id, DocumentId) :- star_relation(DocumentId, _Subject, _Predicate, Id, _D, _N, _C, _S, _E).
related_document(Id, DocumentId) :- star_ref(DocumentId, _Path, Id).

tool_timeline(Id, time(DocumentId, Key, Value, Path)) :-
    related_document(Id, DocumentId),
    star_time(DocumentId, Key, Value, Path).

tool_contradictions(Id, relation_conflict(PositiveId, NegativeId, Subject, Predicate, Object)) :-
    star_relation(PositiveId, Subject, Predicate, Object, _D1, false, _C1, _S1, _E1),
    star_relation(NegativeId, Subject, Predicate, Object, _D2, true, _C2, _S2, _E2),
    (Subject = Id ; Object = Id).
tool_contradictions(Id, evidence_conflict(DocumentId, EvidenceId, ContradictedEvidenceId)) :-
    related_document(Id, DocumentId),
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

related_source(Id, source(DocumentId, SourceId, Kind, Locator, Credibility, Reliability, Hash)) :-
    related_document(Id, DocumentId),
    star_source(DocumentId, SourceId, Kind, Locator, Credibility, Reliability, Hash).
related_source(Id, provenance(DocumentId, Collector, Actor, Tool, Model, RunId, Method, ImportedFrom, Transform)) :-
    related_document(Id, DocumentId),
    star_provenance(DocumentId, Collector, Actor, Tool, Model, RunId, Method, ImportedFrom, Transform).

tool_why_not(Subject, Predicate, Object, already_supported(RelationId)) :-
    star_relation(RelationId, Subject, Predicate, Object, _Directed, false, _Confidence, _Start, _End), !.
tool_why_not(Subject, Predicate, Object, explicitly_negated(RelationId)) :-
    star_relation(RelationId, Subject, Predicate, Object, _Directed, true, _Confidence, _Start, _End), !.
tool_why_not(Subject, Predicate, Object, missing_direct_relation(Subject, Predicate, Object)).

% Capability routing mirrors STAR-AUTO-RESEARCH-001: callers ask for semantics,
% not a hard-coded engine. The runtime may bind these capabilities to engines.
tool_route_reasoning(_Task, true, true, _Explain, _Bulk, recursive_probabilistic_query).
tool_route_reasoning(_Task, true, false, _Explain, _Bulk, probabilistic_query).
tool_route_reasoning(_Task, false, true, true, false, answer_set_or_tabled_explanation).
tool_route_reasoning(_Task, false, true, false, false, recursive_tabled_query).
tool_route_reasoning(_Task, false, _Recursive, _Explain, true, bulk_datalog_closure).
tool_route_reasoning(_Task, false, false, true, false, deterministic_explanation).
tool_route_reasoning(_Task, false, false, false, false, deterministic_rule_evaluation).

tool_values(Id, Prefix, value(Path, Type, Value)) :-
    star_json_value(Id, Path, Type, Value),
    atom(Prefix),
    sub_atom(Path, 0, _Length, _After, Prefix).

tool_referrers(Target, reference(DocumentId, Path, Target)) :-
    star_ref(DocumentId, Path, Target).

take_at_most(Max, Items, Limited) :-
    integer(Max), Max >= 0,
    ( length(Prefix, Max), append(Prefix, _Rest, Items) -> Limited = Prefix ; Limited = Items ).

tool_packet(Id, MaxItems,
            packet(Document, neighbors(Neighbors), timeline(Timeline),
                   sources(Sources), contradictions(Contradictions))) :-
    ( tool_document(Id, Document0) -> Document = Document0 ; Document = unknown_document(Id) ),
    findall(Edge, tool_neighbors(Id, both, Edge), Edge0), sort(Edge0, Edge1), take_at_most(MaxItems, Edge1, Neighbors),
    findall(Time, tool_timeline(Id, Time), Time0), sort(Time0, Time1), take_at_most(MaxItems, Time1, Timeline),
    findall(Source, related_source(Id, Source), Source0), sort(Source0, Source1), take_at_most(MaxItems, Source1, Sources),
    findall(Conflict, tool_contradictions(Id, Conflict), Conflict0), sort(Conflict0, Conflict1), take_at_most(MaxItems, Conflict1, Contradictions).
