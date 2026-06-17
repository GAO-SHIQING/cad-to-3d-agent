"""节点 3: 人工确认 (LangGraph interrupt)"""

from ..state import AgentState


def confirm_node(state: AgentState) -> AgentState:
    """
    确认节点 — 纯状态节点。

    终端输入由 main.run_with_interrupts 在 LangGraph interrupt 外层处理；
    这里不直接 input()，避免 CLI 和节点重复询问。
    """
    if state.get("user_confirmed"):
        print("[confirm] 已确认，跳过")
        return state

    plan = state.get("modeling_plan", [])

    if not plan:
        if state.get("planning_errors"):
            print(f"[confirm] 没有可确认的建模计划，规划错误: {state.get('planning_errors')}")
            state["user_confirmed"] = False
            return state
        print("[confirm] 没有建模计划，自动通过")
        state["user_confirmed"] = True
        return state

    feedback = state.get("user_feedback", "")
    if feedback:
        print(f"[confirm] 计划未批准，反馈已记录: {feedback}")
    else:
        print(f"[confirm] 等待确认计划: {len(plan)} 个步骤")
    return state
