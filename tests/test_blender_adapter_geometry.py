"""测试 Blender 适配器的尺寸语义。"""


def test_cube_scale_uses_full_dimensions():
    from tools.background_adapter import _cube_scale_for_dimensions

    assert _cube_scale_for_dimensions(4.0, 0.24, 2.8) == (4.0, 0.24, 2.8)


def test_cube_scale_rejects_negative_dimensions():
    from tools.background_adapter import _cube_scale_for_dimensions

    try:
        _cube_scale_for_dimensions(4.0, -0.24, 2.8)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("negative dimensions must be rejected")


def test_post_processing_merge_threshold_stays_below_wall_thickness():
    from agent.nodes.execute import _create_post_processing_commands

    commands = _create_post_processing_commands(
        base_step_id=4,
        output_dir="./output",
        floor_bounds=None,
        wall_height=2.8,
        min_wall_thickness=0.24,
    )

    join = next(cmd for cmd in commands if cmd.operation == "join_and_merge")
    assert join.params["merge_threshold"] <= 0.024


def test_mcp_join_and_merge_keeps_independent_wall_objects():
    from tools.mcp_adapter import _generate_bpy_for_command

    code = _generate_bpy_for_command(
        "join_and_merge",
        {"merge_threshold": 0.01},
        step_id=5,
    )

    assert "BOOLEAN" not in code
    assert "UNION" not in code
    assert "object.join" not in code
    assert "remove_doubles" in code


def test_background_join_and_merge_template_keeps_independent_wall_objects():
    from tools.background_adapter import BPY_SCRIPT_TEMPLATE

    start = BPY_SCRIPT_TEMPLATE.index('elif operation == "join_and_merge":')
    end = BPY_SCRIPT_TEMPLATE.index('elif operation == "create_floor_ceiling":')
    section = BPY_SCRIPT_TEMPLATE[start:end]

    assert "type='BOOLEAN'" not in section
    assert "UNION" not in section
    assert "join()" not in section
    assert "remove_doubles" in section
    assert "independent_walls" in section


def test_plan_walls_extend_by_half_thickness_for_overlap():
    from tools.plan_validator import validate_plan

    cad_features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}, "properties": {"height": 2800, "thickness": 240}},
        {"type": "wall", "geometry": {"start": [4000, 0], "end": [4000, 3000]}, "properties": {"height": 2800, "thickness": 240}},
    ]
    plan = [
        {"step_id": 1, "operation": "extrude_wall", "params": {"start": [0, 0], "end": [4, 0], "height": 2.8, "thickness": 0.24}, "depends_on": []},
        {"step_id": 2, "operation": "extrude_wall", "params": {"start": [4, 0], "end": [4, 3], "height": 2.8, "thickness": 0.24}, "depends_on": [1]},
    ]

    result = validate_plan(plan, cad_features=cad_features)
    assert result["valid"] is True
