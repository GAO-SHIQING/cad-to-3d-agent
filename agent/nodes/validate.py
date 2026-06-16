"""节点 5: 双层验证"""

import json
from ..state import AgentState
from ..llm import chat
from ..prompts import VALIDATE_SYSTEM_PROMPT
from tools.geometry_checker import run_geometry_checks


def validate_node(state: AgentState) -> AgentState:
    """
    验证节点：
    第一层：几何硬校验（确定性代码）
    第二层：LLM 语义验证（合理性检查）

    如果任一层不通过且 revision_count < max_revisions → 回到 execute
    如果通过或超限 → END
    """
    cad_features = state.get("cad_features", [])
    execution_results = state.get("execution_results", [])
    revision_count = state.get("revision_count", 0)

    state["revision_count"] = revision_count + 1
    print(f"[validate] 第 {state['revision_count']}/{state.get('max_revisions', 3)} 次验证")

    # === 第一层：几何硬校验 ===
    geo_result = run_geometry_checks(cad_features, execution_results)

    geo_passed = geo_result.get("geometry_passed", False)
    geo_issues = geo_result.get("issues", [])
    print(f"[validate] 几何检查: {'✅ 通过' if geo_passed else '❌ 不通过'}")
    for issue in geo_issues:
        print(f"  [{issue['severity']}] {issue['entity']}: {issue['description']}")

    # === 第二层：LLM 语义验证 ===
    semantic_passed = True
    semantic_issues = []

    if cad_features and execution_results:
        user_message = json.dumps({
            "cad_features": cad_features,
            "execution_results": execution_results,
            "geometry_issues": geo_issues,
        }, ensure_ascii=False, indent=2)

        try:
            response = chat(
                system_prompt=VALIDATE_SYSTEM_PROMPT,
                user_message=user_message,
                max_tokens=2048,
            )
            response = response.strip()
            if response.startswith("```"):
                response = response.strip("```").strip()
                if response.startswith("json"):
                    response = response[4:].strip()

            sem_result = json.loads(response)
            semantic_passed = sem_result.get("passed", True)
            semantic_issues = sem_result.get("issues", [])
            print(f"[validate] 语义检查: {'✅ 通过' if semantic_passed else '❌ 不通过'}")
            for issue in semantic_issues:
                print(f"  [{issue.get('severity', '?')}] {issue.get('description', '')}")

        except json.JSONDecodeError as e:
            print(f"[validate] LLM 语义验证返回格式错误: {e}")
            semantic_passed = True  # 格式错误不阻塞流程

    # === 汇总 ===
    all_issues = geo_issues + semantic_issues
    overall_passed = geo_passed and semantic_passed

    state["validation_result"] = {
        "overall_passed": overall_passed,
        "geometry_passed": geo_passed,
        "semantic_passed": semantic_passed,
        "issues": all_issues,
        "revision": state["revision_count"],
    }
    state["validation_passed"] = overall_passed

    if overall_passed:
        print("[validate] ✅✅ 全部验证通过！")
    elif state["revision_count"] >= state.get("max_revisions", 3):
        print(f"[validate] ⚠️ 达到最大修订次数 ({state['revision_count']})，输出最佳结果")
    else:
        print(f"[validate] 🔄 将在第 {state['revision_count'] + 1} 次修订中尝试修正")

    return state
