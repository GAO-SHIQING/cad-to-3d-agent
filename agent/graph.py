"""LangGraph StateGraph 定义与编译"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from .state import AgentState
from .nodes import parse_cad_node, plan_node, confirm_node, execute_node, validate_node


def route_confirm(state: AgentState) -> str:
    """确认节点后的路由"""
    if state.get("user_confirmed"):
        return "execute"
    if state.get("user_feedback") == "REDO":
        return "plan"
    return "plan"


def route_validate(state: AgentState) -> str:
    """验证节点后的路由"""
    if state.get("validation_passed"):
        return END
    if state["revision_count"] >= state.get("max_revisions", 3):
        return END
    return "execute"


def build_graph() -> StateGraph:
    """构建并编译 LangGraph 状态图"""
    graph = StateGraph(AgentState)

    # 添加 5 个节点
    graph.add_node("parse", parse_cad_node)
    graph.add_node("plan", plan_node)
    graph.add_node("confirm", confirm_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)

    # 主流程边
    graph.set_entry_point("parse")
    graph.add_edge("parse", "plan")
    graph.add_edge("plan", "confirm")

    # 确认 → 条件路由
    graph.add_conditional_edges("confirm", route_confirm, {
        "execute": "execute",
        "plan": "plan",
    })

    # 执行 → 验证
    graph.add_edge("execute", "validate")

    # 验证 → 条件路由（通过→END，不通过→执行，超限→END）
    graph.add_conditional_edges("validate", route_validate, {
        "execute": "execute",
        END: END,
    })

    return graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["confirm"],
    )
