"""测试确认流程由 CLI 管理，不应在节点内直接读取输入。"""

import builtins

from agent.nodes.confirm import confirm_node


def test_confirm_node_does_not_read_input(monkeypatch):
    called = []

    def fake_input(*args, **kwargs):
        called.append(True)
        raise AssertionError("input() should not be called from confirm_node")

    monkeypatch.setattr(builtins, "input", fake_input)

    state = {
        "modeling_plan": [{"step_id": 1, "operation": "extrude_wall"}],
        "user_confirmed": False,
        "user_feedback": "",
    }

    result = confirm_node(state)

    assert called == []
    assert result is state


def test_confirm_node_keeps_invalid_empty_plan_unconfirmed():
    from agent.nodes.confirm import confirm_node

    state = {
        "modeling_plan": [],
        "planning_errors": ["wall features require at least 2 extrude_wall steps"],
        "user_confirmed": False,
        "user_feedback": "wall features require at least 2 extrude_wall steps",
    }

    result = confirm_node(state)

    assert result["user_confirmed"] is False


def test_auto_confirm_does_not_approve_invalid_empty_plan():
    from main import confirmation_update_for_state

    update = confirmation_update_for_state(
        {
            "modeling_plan": [],
            "planning_errors": ["wall features require at least 2 extrude_wall steps"],
        },
        auto_confirm=True,
        choice="",
    )

    assert update["user_confirmed"] is False
    assert "wall features require" in update["user_feedback"]
