:- module(star_json,
          [ star_projection_manifest/6,
            star_doc/6,
            star_profile/5,
            star_json_object/2,
            star_json_array/3,
            star_json_member/4,
            star_json_index/4,
            star_json_value/4,
            star_ref/3,
            star_time/4,
            star_provenance/9,
            star_source/7,
            star_evidence/7,
            star_evidence_contradicts/3,
            star_evidence_corroborates/3,
            star_relation/9,
            star_inverse_predicate/3,
            star_relation_qualifier/3,
            load_projection/1
          ]).

:- dynamic star_projection_manifest/6.
:- dynamic star_doc/6.
:- dynamic star_profile/5.
:- dynamic star_json_object/2.
:- dynamic star_json_array/3.
:- dynamic star_json_member/4.
:- dynamic star_json_index/4.
:- dynamic star_json_value/4.
:- dynamic star_ref/3.
:- dynamic star_time/4.
:- dynamic star_provenance/9.
:- dynamic star_source/7.
:- dynamic star_evidence/7.
:- dynamic star_evidence_contradicts/3.
:- dynamic star_evidence_corroborates/3.
:- dynamic star_relation/9.
:- dynamic star_inverse_predicate/3.
:- dynamic star_relation_qualifier/3.

load_projection(File) :-
    load_files(File, [module(star_json), if(changed), silent(true)]).
