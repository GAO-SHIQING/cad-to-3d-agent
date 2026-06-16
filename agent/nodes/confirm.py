"""节点 3: 人工确认 (LangGraph interrupt)"""

from ..state import AgentState


def confirm_node(state: AgentState) -> AgentState:
    """
    确认节点 — 展示建模计划并等待用户决定。

    如果之前已经确认过（user_confirmed=True），跳过。
    否则展示计划，等待用户输入。
    """
    if state.get("user_confirmed"):
        print("[confirm] 已确认，跳过")
        return state

    plan = state.get("modeling_plan", [])

    if not plan:
        print("[confirm] 没有建模计划，自动通过")
        state["user_confirmed"] = True
        return state

    # === 展示计划摘要 ===
    print("\n" + "=" * 60)
    print("📋 建模计划")
    print("=" * 60)
    print(f"共 {len(plan)} 个步骤：\n")

    for step in plan:
        sid = step.get("step_id", "?")
        op = step.get("operation", "?")
        deps = step.get("depends_on", [])
        dep_str = f" (依赖步骤: {deps})" if deps else ""
        print(f"  步骤 {sid}: {op}{dep_str}")

    print("\n" + "-" * 40)
    print("请选择操作：")
    print("  [y] 批准，继续执行")
    print("  [n] 重做规划")
    print("  [修改指令] 输入任意文字来修改计划（如：'把层高改成3米'）")
    print("-" * 40)

    user_input = input("> ").strip()

    if user_input.lower() in ("y", "yes", ""):
        state["user_confirmed"] = True
        print("[confirm] ✅ 计划已批准")
    elif user_input.lower() in ("n", "no", "REDO"):
        state["user_confirmed"] = False
        state["user_feedback"] = "REDO"
        print("[confirm] 🔄 重新规划")
    else:
        state["user_confirmed"] = False
        state["user_feedback"] = user_input
        print(f"[confirm] 📝 修改指令已记录: {user_input}")

    return state
