"""测试 AgentState 结构和初始状态"""

from agent.state import AgentState


def test_agent_state_structure():
    """验证 AgentState 包含所有必需字段"""
    state: AgentState = {
        "cad_path": "",
        "user_instruction": "",
        "raw_geometry": [],
        "cad_features": [],
        "modeling_plan": [],
        "user_confirmed": False,
        "user_feedback": "",
        "execution_mode": "background",
        "current_step": 0,
        "execution_results": [],
        "blender_output_path": "",
        "render_images": [],
        "validation_result": {},
        "revision_count": 0,
        "max_revisions": 3,
        "quality_score": 0.0,
        "validation_passed": False,
    }
    assert state["revision_count"] == 0
    assert state["max_revisions"] == 3
    assert state["execution_mode"] == "background"
    assert state["quality_score"] == 0.0
    assert len(state["cad_features"]) == 0
