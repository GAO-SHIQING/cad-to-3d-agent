"""测试建模计划在进入 Blender 前的校验和归一化。"""


def test_plan_validator_rejects_unknown_operation():
    from tools.plan_validator import validate_plan

    result = validate_plan([
        {"step_id": 1, "operation": "explode_room", "params": {}, "depends_on": []},
    ])

    assert result["valid"] is False
    assert any("explode_room" in error for error in result["errors"])


def test_plan_validator_fills_missing_step_fields():
    from tools.plan_validator import validate_plan

    result = validate_plan([
        {"operation": "extrude_wall", "params": {"start": [0, 0], "end": [4, 0]}}
    ])

    assert result["valid"] is True
    assert result["plan"][0]["step_id"] == 1
    assert result["plan"][0]["depends_on"] == []


def test_plan_validator_converts_numeric_strings():
    from tools.plan_validator import validate_plan

    result = validate_plan([
        {
            "step_id": 2,
            "operation": "place_door",
            "params": {"location": ["2.5", "0.0", "0.0"], "width": "0.9"},
            "depends_on": [1],
        }
    ])

    assert result["valid"] is True
    assert result["plan"][0]["params"]["location"] == [2.5, 0.0, 0.0]


def test_plan_validator_rejects_non_numeric_coordinates():
    from tools.plan_validator import validate_plan

    result = validate_plan([
        {
            "step_id": 1,
            "operation": "extrude_wall",
            "params": {"start": ["a", 0], "end": [4, 0]},
            "depends_on": [],
        }
    ])

    assert result["valid"] is False
    assert any("must be a numeric" in error for error in result["errors"])


def test_plan_validator_rejects_missing_wall_operations_for_wall_features():
    from tools.plan_validator import validate_plan

    cad_features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4, 0]}, "properties": {}},
        {"type": "wall", "geometry": {"start": [4, 0], "end": [4, 3]}, "properties": {}},
    ]
    plan = [
        {"operation": "extrude_wall", "params": {"start": [0, 0], "end": [4, 0]}},
    ]

    result = validate_plan(plan, cad_features=cad_features)

    assert result["valid"] is False
    assert any("wall features require" in error for error in result["errors"])


def test_repair_plan_adds_missing_wall_operations_from_features():
    from tools.plan_validator import repair_plan_from_features, validate_plan

    cad_features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}, "properties": {"height": 2800, "thickness": 240}},
        {"type": "wall", "geometry": {"start": [4000, 0], "end": [4000, 3000]}, "properties": {"height": 2800, "thickness": 240}},
        {"type": "wall", "geometry": {"start": [4000, 3000], "end": [0, 3000]}, "properties": {"height": 2800, "thickness": 240}},
    ]
    plan = [
        {
            "step_id": 1,
            "operation": "extrude_wall",
            "params": {"start": [0, 0], "end": [4, 0], "wall_id": "wall_01"},
            "depends_on": [],
        }
    ]

    repaired = repair_plan_from_features(plan, cad_features)
    validation = validate_plan(repaired, cad_features=cad_features)
    wall_steps = [step for step in repaired if step["operation"] == "extrude_wall"]

    assert validation["valid"] is True
    assert len(wall_steps) == 3
    assert wall_steps[1]["params"]["start"] == [4.0, 0.0]
    assert wall_steps[1]["params"]["end"] == [4.0, 3.0]


def test_plan_node_repairs_missing_wall_steps_before_validation(monkeypatch):
    from agent.nodes.plan import plan_node

    captured = {}

    def fake_chat(*, system_prompt, user_message, **kwargs):
        captured["user_message"] = user_message
        return (
            '[{"operation": "extrude_wall", "params": {"start": [0, 0], "end": [4, 0]}}]'
        )

    monkeypatch.setattr("agent.nodes.plan.chat", fake_chat)

    state = {
        "cad_features": [
            {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}, "properties": {"height": 2800, "thickness": 240}},
            {"type": "wall", "geometry": {"start": [4000, 0], "end": [4000, 3000]}, "properties": {"height": 2800, "thickness": 240}},
            {"type": "wall", "geometry": {"start": [4000, 3000], "end": [0, 3000]}, "properties": {"height": 2800, "thickness": 240}},
        ],
        "user_instruction": "",
        "user_feedback": "",
    }

    result = plan_node(state)

    assert len(result["modeling_plan"]) == 3
    assert result["planning_errors"] == []


def test_repair_plan_adds_missing_opening_cut_and_door_from_features():
    from tools.plan_validator import repair_plan_from_features, validate_plan

    cad_features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}, "properties": {"height": 2800, "thickness": 240}},
        {"type": "door", "geometry": {"vertices": [[1500, 0], [2500, 0]]}, "properties": {"width": 1000, "height": 2100}},
    ]
    plan = [
        {
            "step_id": 1,
            "operation": "extrude_wall",
            "params": {"wall_id": "wall_01", "start": [0, 0], "end": [4, 0], "height": 2.8, "thickness": 0.24},
            "depends_on": [],
        }
    ]

    repaired = repair_plan_from_features(plan, cad_features)
    validation = validate_plan(repaired, cad_features=cad_features)
    operations = [step["operation"] for step in repaired]

    assert validation["valid"] is True
    assert "boolean_cut" in operations
    assert "place_door" in operations
    cut = next(step for step in repaired if step["operation"] == "boolean_cut")
    assert cut["params"]["target_wall_id"] == "wall_01"
    assert cut["params"]["location"] == [2.0, 0.0, 1.05]


def test_plan_node_falls_back_to_deterministic_plan_when_llm_fails(monkeypatch):
    from agent.nodes.plan import plan_node

    def boom(*args, **kwargs):
        raise RuntimeError("plan timeout")

    monkeypatch.setattr("agent.nodes.plan.chat", boom)

    state = {
        "cad_features": [
            {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}, "properties": {"height": 2800, "thickness": 240}},
            {"type": "door", "geometry": {"vertices": [[1500, 0], [2500, 0]]}, "properties": {"width": 1000, "height": 2100}},
        ],
        "user_instruction": "",
        "user_feedback": "",
    }

    result = plan_node(state)
    operations = [step["operation"] for step in result["modeling_plan"]]

    assert operations == ["extrude_wall", "boolean_cut", "place_door"]
    assert result["planning_errors"] == []
