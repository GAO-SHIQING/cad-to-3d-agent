"""节点 2: 操作级建模规划"""

import json
from ..state import AgentState
from ..llm import chat
from ..prompts import PLAN_SYSTEM_PROMPT


def plan_node(state: AgentState) -> AgentState:
    """
    建模规划节点：
    接收 cad_features → LLM 推理建模顺序和参数 →
    输出 modeling_plan（操作序列）。
    """
    features = state.get("cad_features", [])
    user_feedback = state.get("user_feedback", "")

    if not features:
        state["modeling_plan"] = []
        print("[plan] 没有建筑实体，跳过规划")
        return state

    # 如果有用户修改反馈，拼接到 prompt 中
    feedback_text = ""
    if user_feedback and user_feedback != "REDO":
        feedback_text = f"\n\n## 用户修改要求\n{user_feedback}\n请根据以上要求调整规划。"

    # 将 cad_features 序列化为文本
    features_text = json.dumps(features, ensure_ascii=False, indent=2)

    user_message = f"## 建筑实体\n{features_text}{feedback_text}"

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

        # 确保每个步骤有 step_id
        for i, step in enumerate(plan):
            if "step_id" not in step:
                step["step_id"] = i + 1
            if "depends_on" not in step:
                step["depends_on"] = []

        state["modeling_plan"] = plan
        state["user_feedback"] = ""  # 消费掉反馈
        print(f"[plan] 生成了 {len(plan)} 个建模步骤")

    except json.JSONDecodeError as e:
        print(f"[plan] LLM 返回格式错误: {e}")
        state["modeling_plan"] = []
        state["user_feedback"] = ""

    return state
