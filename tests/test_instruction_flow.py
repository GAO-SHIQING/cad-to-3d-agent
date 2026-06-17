"""测试用户指令和验证反馈能进入重新规划流程。"""


def test_plan_node_includes_user_instruction(monkeypatch):
    from agent.nodes.plan import plan_node

    captured = {}

    def fake_chat(*, system_prompt, user_message, **kwargs):
        captured["user_message"] = user_message
        return "[]"

    monkeypatch.setattr("agent.nodes.plan.chat", fake_chat)

    state = {
        "cad_features": [{"type": "wall", "geometry": {}, "properties": {}}],
        "user_instruction": "层高改为3米",
        "user_feedback": "",
    }

    plan_node(state)

    assert "层高改为3米" in captured["user_message"]


def test_plan_node_includes_validation_feedback(monkeypatch):
    from agent.nodes.plan import plan_node

    captured = {}

    def fake_chat(*, system_prompt, user_message, **kwargs):
        captured["user_message"] = user_message
        return "[]"

    monkeypatch.setattr("agent.nodes.plan.chat", fake_chat)

    state = {
        "cad_features": [{"type": "wall", "geometry": {}, "properties": {}}],
        "user_instruction": "",
        "user_feedback": "请修正墙体闭合问题",
    }

    plan_node(state)

    assert "请修正墙体闭合问题" in captured["user_message"]


def test_validate_failure_resets_confirmation(monkeypatch):
    from agent.nodes.validate import validate_node

    def fake_run_geometry_checks(*args, **kwargs):
        return {
            "geometry_passed": False,
            "checks": [],
            "issues": [
                {
                    "severity": "error",
                    "entity": "wall_01",
                    "description": "墙体未闭合",
                    "suggestion": "调整墙体端点",
                }
            ],
        }

    monkeypatch.setattr("agent.nodes.validate.run_geometry_checks", fake_run_geometry_checks)
    monkeypatch.setattr("agent.nodes.validate.render_dxf_to_base64", lambda *args, **kwargs: None)

    state = {
        "cad_path": "examples/single_room.dxf",
        "cad_features": [],
        "execution_results": [],
        "render_images": [],
        "revision_count": 0,
        "max_revisions": 3,
        "user_confirmed": True,
        "user_feedback": "",
    }

    result = validate_node(state)

    assert result["validation_passed"] is False
    assert result["user_confirmed"] is False
    assert "墙体未闭合" in result["user_feedback"]


def test_parse_node_falls_back_when_vision_fails(monkeypatch):
    from agent.nodes.parse import parse_cad_node

    monkeypatch.setattr("agent.nodes.parse.render_dxf_to_base64", lambda *args, **kwargs: "img")

    def boom(*args, **kwargs):
        raise RuntimeError("vision timeout")

    monkeypatch.setattr("agent.nodes.parse.chat_with_vision", boom)

    state = {"cad_path": "file/2.dxf"}
    result = parse_cad_node(state)

    types = {feature["type"] for feature in result["cad_features"]}
    assert "wall" in types
    assert "door" in types
    assert "window" in types


def test_parse_and_plan_fallback_produces_valid_plan(monkeypatch):
    from agent.nodes.parse import parse_cad_node
    from agent.nodes.plan import plan_node

    monkeypatch.setattr("agent.nodes.parse.render_dxf_to_base64", lambda *args, **kwargs: "img")
    monkeypatch.setattr("agent.nodes.parse.chat_with_vision", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vision timeout")))
    monkeypatch.setattr("agent.nodes.plan.chat", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("plan timeout")))

    state = parse_cad_node({"cad_path": "file/2.dxf"})
    state.update({"user_instruction": "", "user_feedback": ""})
    result = plan_node(state)

    wall_steps = [step for step in result["modeling_plan"] if step["operation"] == "extrude_wall"]
    wall_features = [feature for feature in result["cad_features"] if feature["type"] == "wall"]

    assert result["planning_errors"] == []
    assert len(wall_steps) >= len(wall_features)
    assert any(step["operation"] == "place_door" for step in result["modeling_plan"])
    assert any(step["operation"] == "place_window" for step in result["modeling_plan"])
