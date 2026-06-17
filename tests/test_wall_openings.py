"""测试墙体闭合和门窗开洞约束。"""


def test_disconnected_joined_wall_components_are_warnings():
    from tools.geometry_checker import check_scene_wall_components

    result = check_scene_wall_components({
        "objects": [
            {"name": "wall_01", "type": "MESH", "component_count": 5},
            {"name": "window_01", "type": "MESH", "component_count": 1},
        ]
    })

    assert result["passed"] is True
    assert result["issues"][0]["severity"] == "warning"


def test_door_window_features_require_boolean_cut_steps():
    from tools.plan_validator import validate_plan

    cad_features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4, 0]}, "properties": {}},
        {"type": "door", "geometry": {"center": [2, 0]}, "properties": {"width": 0.9}},
    ]
    plan = [
        {"step_id": 1, "operation": "extrude_wall", "params": {"start": [0, 0], "end": [4, 0]}, "depends_on": []},
        {"step_id": 2, "operation": "place_door", "params": {"location": [2, 0, 0], "width": 0.9}, "depends_on": [1]},
    ]

    result = validate_plan(plan, cad_features=cad_features)

    assert result["valid"] is False
    assert any("boolean_cut" in error for error in result["errors"])


def test_mcp_boolean_cut_params_preserve_rotation_and_wall_thickness():
    from tools.mcp_adapter import validate_params

    params = validate_params(
        "boolean_cut",
        {
            "target_wall_id": "wall_01",
            "location": [2.0, 0.0, 1.05],
            "dimensions": [0.9, 0.3, 2.1],
            "rotation_z": 1.57,
            "wall_thickness": 0.24,
        },
    )

    assert params["rotation_z"] == 1.57
    assert params["wall_thickness"] == 0.24


def test_multiple_wall_scene_objects_are_errors():
    from tools.geometry_checker import check_scene_wall_components

    result = check_scene_wall_components({
        "objects": [
            {"name": "wall_01", "type": "MESH", "component_count": 1},
            {"name": "wall_02", "type": "MESH", "component_count": 1},
        ]
    })

    assert result["passed"] is False
    assert result["issues"][0]["severity"] == "error"
