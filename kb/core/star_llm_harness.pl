:- module(star_llm_harness,
          [ validate_plan_file/1,
            validate_plan/1
          ]).

:- use_module(library(http/json)).
:- use_module(library(lists)).

validate_plan_file(Path) :-
    setup_call_cleanup(
        open(Path, read, Stream, [encoding(utf8)]),
        json_read_dict(Stream, Plan),
        close(Stream)),
    validate_plan(Plan).

validate_plan(Plan) :-
    require_dict(Plan, plan),
    require_string_field(Plan, schema, Schema),
    ( Schema == "starintel.llm.plan.v1" -> true ; reject(invalid_schema) ),
    require_string_field(Plan, goal, _),
    require_list_field(Plan, steps, Steps),
    ( Steps == [] -> reject(empty_steps) ; true ),
    maplist(validate_step_shape, Steps),
    step_ids(Steps, Ids),
    sort(Ids, UniqueIds),
    ( same_length(Ids, UniqueIds)
    -> validate_dependencies(Steps, Ids),
       ( has_cycle(Steps) -> reject(cyclic_dependencies) ; true )
    ;  reject(duplicate_step_id)
    ).

validate_step_shape(Step) :-
    require_dict(Step, step),
    require_string_field(Step, id, _),
    require_string_field(Step, kind, Kind),
    ( Kind == "model" -> true ; reject(invalid_step_kind) ),
    require_string_field(Step, provider, _),
    require_string_field(Step, prompt, _),
    require_list_field(Step, depends_on, Dependencies),
    maplist(require_nonempty_string, Dependencies).

step_ids(Steps, Ids) :-
    maplist(step_id, Steps, Ids).

step_id(Step, Id) :-
    get_dict(id, Step, Id).

validate_dependencies([], _).
validate_dependencies([Step|Rest], Ids) :-
    get_dict(id, Step, Id),
    get_dict(depends_on, Step, Dependencies),
    maplist(validate_dependency(Id, Ids), Dependencies),
    validate_dependencies(Rest, Ids).

validate_dependency(Id, Ids, Dependency) :-
    ( Dependency == Id -> reject(self_dependency) ; true ),
    ( memberchk(Dependency, Ids) -> true ; reject(missing_dependency) ).

has_cycle(Steps) :-
    member(Step, Steps),
    get_dict(id, Step, Id),
    dependency_reaches(Steps, Id, Id, []),
    !.

dependency_reaches(Steps, Current, Target, Seen) :-
    step_by_id(Steps, Current, Step),
    get_dict(depends_on, Step, Dependencies),
    member(Dependency, Dependencies),
    ( Dependency == Target
    ; \+ memberchk(Dependency, Seen),
      dependency_reaches(Steps, Dependency, Target, [Dependency|Seen])
    ).

step_by_id(Steps, Id, Step) :-
    member(Step, Steps),
    get_dict(id, Step, Id),
    !.

require_dict(Value, _) :-
    is_dict(Value),
    !.
require_dict(_, Field) :-
    reject(expected_dict(Field)).

require_list_field(Dict, Field, Value) :-
    ( get_dict(Field, Dict, Value), is_list(Value)
    -> true
    ;  reject(expected_list(Field))
    ).

require_string_field(Dict, Field, Value) :-
    ( get_dict(Field, Dict, Value), require_nonempty_string(Value)
    -> true
    ;  reject(expected_string(Field))
    ).

require_nonempty_string(Value) :-
    string(Value),
    string_length(Value, Length),
    Length > 0.

reject(Code) :-
    throw(error(star_llm_plan_validation(Code), _)).
