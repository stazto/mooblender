# Test fixtures and regression coverage

The test suite does not contain copied Mooble catalog packages. Synthetic PMob
records, ZIP members, images, and malformed inputs are assembled in Python from
`bytes` values and standard-library builders. Do not add binary fixture files.
`test_fixture_policy.py` enforces that rule in the normal CI matrix.

The named model regressions preserve only the minimum observed metadata or
geometry responsible for each failure:

| Reported model or behavior | Offline regression | Blender integration |
| --- | --- | --- |
| Nested instances, optional realization, and interface panels | — | `test_modifier_keeps_nested_instances_until_top_option_realizes_them` and `blender_smoke.py` |
| Ônix kitchen-kit root scale | `test_onix_kitchen_kit_preserves_root_scale_and_millimetre_translation` | root transform in `blender_smoke.py` |
| 728 mirrored doors and labels | `test_728_pair_has_named_independent_symmetric_outward_door_motions` | independent single-value controls in `blender_smoke.py` |
| 728 stretching, fixed handles, generated UVs | dimension and opening primitives | resized panel/hardware/UV checks in `blender_smoke.py` |
| PE27 width and depth controls | `test_pe27_exposes_width_and_depth_but_not_fixed_height` | axis-specific modifier resizing in `blender_smoke.py` |
| R678 fixed door and black handle | `test_r678_constant_door_metadata_is_distinct_from_variable_dimensions` | `test_r678_constant_door_only_exposes_opening_and_keeps_black_handle` |
| C67 model-selected door, Tampo/Rodapé, and reversal | `test_customization.py` and `test_model_information_selects_conditional_aggregate` | `test_c67_imports_selected_door_and_exposes_optional_components` |
| SUP01.0003 drawer alternatives | `test_sup01_0003_selects_only_one_drawer_body_variant` | aggregate visibility in `blender_smoke.py` |
| 44950/007 drawing-depth placement | `test_44950_007_positions_drawers_from_drawing_depth_not_mesh_envelope` | aggregate parent-dimension placement in `blender_smoke.py` |
| 10122 side-attached handles | `test_10122_handle_source_dimensions_include_primitive_transforms` | `test_10122_side_normal_rotation_keeps_local_front_height_positive` |
| 4220A/0079K shared texel density | `test_4220a_shared_material_components_retain_same_geometry_scale` | final physical UV checks in `blender_smoke.py` |
| Duplicate vertices and smooth surfaces | `test_topology.py` and the named model regression | custom normals, UV seams, and optional quads in `blender_smoke.py` |
| Porta de Giro 31 | `test_porta_de_giro_31_resolves_long_parent_dimension_variables` | long-form aggregate variables in `blender_smoke.py` |
| Porta de Correr 21 | `test_porta_de_correr_21_distributes_three_panels_across_frame` | long-form aggregate variables in `blender_smoke.py` |
| ELA-2 opposing lift carriages | — | `test_ela_2_opposing_side_normals_keep_both_carriages_above_anchor` |
| C66/C69 coupled options, mirrored normals, instanced finishes, and concise finish names | `test_customization.py` | `test_c66_mirror_and_inverted_parts_preserve_outward_face_orientation`, `test_finish_names_use_main_or_the_available_component_name`, and `blender_smoke.py` |
| PE12A opaque/metallic glass and repeated/opaque planar logo | PMob refraction parsing in `test_pmob.py` | `test_pe12a_refraction_factor_creates_alpha_blended_glass` and `test_planar_logo_preserves_uv_scale_alpha_and_serialized_opacity` |

Catalog synchronization, local-only search/navigation, category membership,
manufacturer and collection filters, parallel snapshot creation, asynchronous
work, and on-demand previews have focused tests in `test_catalog_store.py`,
`test_catalog_search.py`, and `test_background.py`. The one live Mooble health
check remains opt-in and runs outside the normal Python matrix.
