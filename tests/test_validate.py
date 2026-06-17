"""测试验证节点的通过/失败门槛。"""


def test_geometry_error_blocks_validation_even_when_l2_passes(monkeypatch):
    from agent.config import Config
    from agent.nodes.validate import validate_node

    def fake_geometry(*args, **kwargs):
        return {
            "geometry_passed": False,
            "blocking_errors": [
                {"severity": "error", "entity": "wall", "description": "missing wall", "suggestion": "add wall"}
            ],
            "issues": [
                {"severity": "error", "entity": "wall", "description": "missing wall", "suggestion": "add wall"}
            ],
            "checks": [],
        }

    monkeypatch.setattr("agent.nodes.validate.run_geometry_checks", fake_geometry)
    monkeypatch.setattr("agent.nodes.validate.render_dxf_to_base64", lambda *args, **kwargs: "cad")
    monkeypatch.setattr("agent.nodes.validate._read_image_base64", lambda *args, **kwargs: "model")
    monkeypatch.setattr(
        "agent.nodes.validate.chat_with_multiple_images",
        lambda *args, **kwargs: '{"passed": true, "confidence": 100, "issues": []}',
    )
    monkeypatch.setattr(Config, "QUALITY_THRESHOLD", 50.0)

    state = {
        "cad_path": "examples/single_room.dxf",
        "cad_features": [],
        "execution_results": [],
        "render_images": ["output/render_00.png"],
        "revision_count": 0,
        "max_revisions": 3,
        "user_feedback": "",
    }

    result = validate_node(state)

    assert result["validation_passed"] is False
    assert result["validation_result"]["blocking_errors"]


def test_geometry_pass_without_l2_is_partial_validation(monkeypatch):
    from agent.nodes.validate import validate_node

    def fake_geometry(*args, **kwargs):
        return {
            "geometry_passed": True,
            "blocking_errors": [],
            "issues": [],
            "checks": [],
        }

    monkeypatch.setattr("agent.nodes.validate.run_geometry_checks", fake_geometry)
    monkeypatch.setattr("agent.nodes.validate.render_dxf_to_base64", lambda *args, **kwargs: None)

    state = {
        "cad_path": "examples/single_room.dxf",
        "cad_features": [],
        "execution_results": [],
        "render_images": [],
        "revision_count": 0,
        "max_revisions": 3,
        "user_feedback": "",
    }

    result = validate_node(state)

    assert result["validation_passed"] is True
    assert result["partial_validation"] is True
