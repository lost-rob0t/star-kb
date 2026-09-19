:- module(star_longterm,
          [ relation_maturity/5,
            linkage_edge/7,
            tool_relation_maturity/4,
            tool_linkage_neighbors/4,
            tool_fact_history/3
          ]).

:- use_module(star_json).

% Maturity is about support for an explicit canonical relation/reference.
% It is not a score for a person, risk, intent, guilt, or identity.

maturity_name(1, referenced).
maturity_name(2, asserted).
maturity_name(3, sourced).
maturity_name(4, corroborated).
maturity_name(5, verified).

source_count(RelationId, Count) :-
    findall(SourceId,
            star_source(RelationId, SourceId, _Kind, _Locator, _Credibility, _Reliability, _Hash),
            Raw),
    sort(Raw, Sources),
    length(Sources, Count).

evidence_count(RelationId, Count) :-
    findall(EvidenceId,
            star_evidence(RelationId, EvidenceId, _SourceId, _Role, _Claim, _Confidence, _Status),
            Raw),
    sort(Raw, Evidence),
    length(Evidence, Count).

verified_evidence(RelationId) :-
    star_evidence(RelationId, _EvidenceId, _SourceId, _Role, _Claim, _Confidence, verified), !.
verified_evidence(RelationId) :-
    star_relation_qualifier(RelationId, status, verified), !.
verified_evidence(RelationId) :-
    star_relation_qualifier(RelationId, verification, verified), !.
verified_evidence(RelationId) :-
    star_relation_qualifier(RelationId, status, confirmed), !.
verified_evidence(RelationId) :-
    star_relation_qualifier(RelationId, verification, confirmed).

relation_contested(RelationId, true) :-
    star_relation(RelationId, Subject, Predicate, Object, _Directed, false, _Confidence, _Start, _End),
    star_relation(OtherId, Subject, Predicate, Object, _D2, true, _C2, _S2, _E2),
    OtherId \= RelationId, !.
relation_contested(RelationId, true) :-
    star_evidence_contradicts(RelationId, _EvidenceId, _OtherEvidenceId), !.
relation_contested(_RelationId, false).

relation_maturity(RelationId, Level, Name, SourceCount, EvidenceCount) :-
    star_relation(RelationId, _Subject, _Predicate, _Object, _Directed, false, _Confidence, _Start, _End),
    source_count(RelationId, SourceCount),
    evidence_count(RelationId, EvidenceCount),
    relation_maturity_level(RelationId, SourceCount, EvidenceCount, Level),
    maturity_name(Level, Name).

relation_maturity_level(RelationId, SourceCount, EvidenceCount, 5) :-
    verified_evidence(RelationId),
    SourceCount >= 1,
    EvidenceCount >= 1, !.
relation_maturity_level(_RelationId, SourceCount, EvidenceCount, 4) :-
    SourceCount >= 2,
    EvidenceCount >= 2, !.
relation_maturity_level(_RelationId, SourceCount, _EvidenceCount, 3) :-
    SourceCount >= 1, !.
relation_maturity_level(_RelationId, _SourceCount, EvidenceCount, 3) :-
    EvidenceCount >= 1, !.
relation_maturity_level(_RelationId, _SourceCount, _EvidenceCount, 2).

linkage_edge(Entity, Other, Predicate, RelationId, Level, Name, Contested) :-
    star_relation(RelationId, Subject, Predicate, Object, _Directed, false, _Confidence, _Start, _End),
    ( (Subject = Entity, Object = Other)
    ; (Object = Entity, Subject = Other)
    ),
    relation_maturity(RelationId, Level, Name, _SourceCount, _EvidenceCount),
    relation_contested(RelationId, Contested).

linkage_edge(Entity, Other, references(Path), reference(Entity, Path, Other), 1, referenced, false) :-
    star_ref(Entity, Path, Other).
linkage_edge(Entity, Other, referenced_by(Path), reference(Other, Path, Entity), 1, referenced, false) :-
    star_ref(Other, Path, Entity).

take_at_most(Max, Items, Limited) :-
    integer(Max), Max >= 0,
    ( length(Prefix, Max), append(Prefix, _Rest, Items) -> Limited = Prefix ; Limited = Items ).

tool_relation_maturity(Subject, Predicate, Object,
                       relation_maturity(Relations)) :-
    findall(
        relation(RelationId,
                 level(Level, Name),
                 sources(SourceCount),
                 evidence(EvidenceCount),
                 confidence(Confidence),
                 interval(Start, End),
                 contested(Contested)),
        ( star_relation(RelationId, Subject, Predicate, Object, _Directed, false,
                        Confidence, Start, End),
          relation_maturity(RelationId, Level, Name, SourceCount, EvidenceCount),
          relation_contested(RelationId, Contested)
        ),
        Raw),
    sort(Raw, Relations).

tool_linkage_neighbors(Entity, MinLevel, MaxItems, linkage(Limited)) :-
    integer(MinLevel), between(1, 5, MinLevel),
    integer(MaxItems), MaxItems >= 1,
    findall(
        edge(Other, Predicate, Evidence, level(Level, Name), contested(Contested)),
        ( linkage_edge(Entity, Other, Predicate, Evidence, Level, Name, Contested),
          Level >= MinLevel
        ),
        Raw),
    sort(Raw, Edges),
    take_at_most(MaxItems, Edges, Limited).

related_document(Id, Id).
related_document(Id, DocumentId) :-
    star_relation(DocumentId, Id, _Predicate, _Object, _Directed, _Negated, _Confidence, _Start, _End).
related_document(Id, DocumentId) :-
    star_relation(DocumentId, _Subject, _Predicate, Id, _Directed, _Negated, _Confidence, _Start, _End).
related_document(Id, DocumentId) :-
    star_ref(DocumentId, _Path, Id).

tool_fact_history(Id, MaxItems, history(Limited)) :-
    integer(MaxItems), MaxItems >= 1,
    findall(
        item(DocumentId, Key, Value, Path),
        ( related_document(Id, DocumentId),
          star_time(DocumentId, Key, Value, Path)
        ),
        Raw),
    sort(Raw, History),
    take_at_most(MaxItems, History, Limited).
