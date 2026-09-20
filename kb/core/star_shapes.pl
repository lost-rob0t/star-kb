:- module(star_shapes,
          [ star_shape_manifest/4,
            star_dtype_count/2,
            star_field_shape/5,
            star_field_cardinality/4,
            star_field_exemplar/3,
            star_relation_shape/4,
            star_qualifier_shape/4,
            star_temporal_key/3,
            star_ref_shape/3,
            load_shapes/1
          ]).

% Candidate fact-shape/ontology facts mined from canonical StarIntel JSON by
% `prolog-star-kb mine-shapes`. They are rebuildable derived evidence, never
% trusted canonical truth.

:- dynamic star_shape_manifest/4.
:- dynamic star_dtype_count/2.
:- dynamic star_field_shape/5.
:- dynamic star_field_cardinality/4.
:- dynamic star_field_exemplar/3.
:- dynamic star_relation_shape/4.
:- dynamic star_qualifier_shape/4.
:- dynamic star_temporal_key/3.
:- dynamic star_ref_shape/3.

% Mined shape files group facts per shape family; clauses may interleave.
:- discontiguous
    star_dtype_count/2, star_field_shape/5, star_field_cardinality/4,
    star_field_exemplar/3, star_relation_shape/4, star_qualifier_shape/4,
    star_temporal_key/3, star_ref_shape/3.

load_shapes(File) :-
    load_files(File, [module(star_shapes), if(changed), silent(true)]).
