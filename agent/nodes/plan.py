"""节点 2: 操作级建模规划"""

import json
from ..state import AgentState
from ..llm import chat
from ..prompts import PLAN_SYSTEM_PROMPT
from tools.plan_validator import repair_plan_from_features, validate_plan


def plan_node(state: AgentState) -> AgentState:
    """
    建模规划节点：
    接收 cad_features → LLM 推理建模顺序和参数 →
    输出 modeling_plan（操作序列）。
    """
    features = state.get("cad_features", [])
    user_instruction = state.get("user_instruction", "")
    user_feedback = state.get("user_feedback", "")

    if not features:
        state["modeling_plan"] = []
        print("[plan] 没有建筑实体，跳过规划")
        return state

    # 初始指令和修正反馈都要进入规划上下文。
    instruction_text = ""
    if user_instruction:
        instruction_text = f"\n\n## 初始用户指令\n{user_instruction}\n请优先满足该要求。"

    if user_feedback and user_feedback != "REDO":
        instruction_text += f"\n\n## 用户修改/验证反馈\n{user_feedback}\n请根据以上要求调整规划。"

    # 将 cad_features 序列化为文本
    features_text = json.dumps(features, ensure_ascii=False, indent=2)

    user_message = f"## 建筑实体\n{features_text}{instruction_text}"

    try:
        response = chat(
            system_prompt=PLAN_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=4096,
        )
        response = response.strip()
        if response.startswith("```"):
            response = response.strip("```").strip()
            if response.startswith("json"):
                response = response[4:].strip()

        plan = json.loads(response)
        if isinstance(plan, dict):
            plan = [plan]

    except Exception as e:
        print(f"[plan] LLM 规划失败，启用确定性兜底: {e}")
        plan = []

    # 确保每个步骤有 step_id
    for i, step in enumerate(plan):
        if "step_id" not in step:
            step["step_id"] = i + 1
        if "depends_on" not in step:
            step["depends_on"] = []

    repaired_plan = repair_plan_from_features(plan, features)
    if len(repaired_plan) != len(plan):
        print(f"[plan] 自动补齐缺失墙段: {len(plan)} -> {len(repaired_plan)}")

    validation = validate_plan(repaired_plan, cad_features=features)
    state["planning_errors"] = validation["errors"]
    state["planning_warnings"] = validation["warnings"]

    if validation["valid"]:
        state["modeling_plan"] = validation["plan"]
    else:
        state["modeling_plan"] = []
        print(f"[plan] 计划校验失败: {validation['errors']}")
        state["user_feedback"] = "\n".join(validation["errors"])
        return state

    state["user_feedback"] = ""  # 消费掉反馈
    print(f"[plan] 生成了 {len(validation['plan'])} 个建模步骤")

    return state
