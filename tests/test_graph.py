"""测试 LangGraph 图编译和路由逻辑"""

from agent.graph import build_graph, route_confirm, route_validate
from agent.state import AgentState


def make_state(**overrides):
    """Helper to create a minimal AgentState for testing"""
    state: AgentState = {
        "cad_path": "", "user_instruction": "",
        "raw_geometry": [], "cad_features": [],
        "modeling_plan": [], "user_confirmed": False, "user_feedback": "",
        "execution_mode": "background", "current_step": 0,
        "execution_results": [], "blender_output_path": "",
        "render_images": [], "validation_result": {},
        "revision_count": 0, "max_revisions": 3, "quality_score": 0.0, "validation_passed": False,
    }
    state.update(overrides)
    return state


def test_build_graph_compile():
    """测试图编译成功"""
    graph = build_graph()
    assert graph is not None
    node_names = set(graph.nodes.keys())
    assert "parse" in node_names
    assert "plan" in node_names
    assert "confirm" in node_names
    assert "execute" in node_names
    assert "validate" in node_names


def test_route_confirm_approved():
    """测试确认路由：批准 → execute"""
    state = make_state(user_confirmed=True)
    assert route_confirm(state) == "execute"


def test_route_confirm_redo():
    """测试确认路由：重做 → plan"""
    state = make_state(user_feedback="REDO")
    assert route_confirm(state) == "plan"


def test_route_validate_passed():
    """测试验证路由：通过 → END"""
    from langgraph.graph import END
    state = make_state(validation_passed=True, revision_count=1)
    assert route_validate(state) == END


def test_route_validate_not_passed_under_limit():
    """测试验证路由：不通过且未超限 → plan（修正循环）"""
    state = make_state(validation_passed=False, revision_count=1)
    assert route_validate(state) == "plan"


def test_route_validate_not_passed_over_limit():
    """测试验证路由：不通过且超限 → END"""
    from langgraph.graph import END
    state = make_state(validation_passed=False, revision_count=3)
    assert route_validate(state) == END
