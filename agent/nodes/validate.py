"""节点 5: 双层验证 + CAD 回看比对循环"""

import base64
import json
from pathlib import Path

from ..state import AgentState
from ..llm import chat_with_multiple_images
from ..prompts import VALIDATE_COMBINED_PROMPT
from ..config import Config
from tools.geometry_checker import run_geometry_checks
from tools.dxf_viewer import render_dxf_to_base64


def _read_image_base64(path: str) -> str | None:
    try:
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except (OSError, FileNotFoundError):
        return None


def _compute_quality_score(
    geo_passed: bool,
    combined_passed: bool,
    combined_confidence: float,
) -> float:
    """综合两层验证结果计算质量评分 (0-100)。

    权重分配：
    - L1 几何硬校验：40 分
    - L2 综合审核（视觉比对+语义检查）：60 分（passed=40 + confidence*0.2）
    """
    score = 0.0
    if geo_passed:
        score += 40.0
    if combined_passed:
        score += 40.0
    score += (combined_confidence / 100.0) * 20.0
    return round(min(score, 100.0), 1)


def _format_feedback(issues: list[dict]) -> str:
    """将 issues 格式化为 plan 节点可读的修正指令"""
    if not issues:
        return ""
    lines = ["请根据以下验证问题修正建模计划："]
    for issue in issues:
        sev = issue.get("severity", "?")
        ent = issue.get("entity", "?")
        desc = issue.get("description", "")
        sug = issue.get("suggestion", "")
        lines.append(f"[{sev}] {ent}: {desc}")
        if sug:
            lines.append(f"  建议: {sug}")
    return "\n".join(lines)


def validate_node(state: AgentState) -> AgentState:
    """
    双层验证 + CAD 回看比对循环：

    L1：几何硬校验（确定性代码，检查实体数量和尺寸）
    L2：综合审核（Vision LLM 单次调用，合并视觉比对和语义检查）

    质量评分 >= QUALITY_THRESHOLD -> 通过
    评分不足且 revision_count < max_revisions -> 将 issues 保存为 user_feedback，
    路由回 plan 节点重新生成修正后的建模计划
    超限 -> 输出当前最佳结果
    """
    cad_path = state.get("cad_path", "")
    cad_features = state.get("cad_features", [])
    execution_results = state.get("execution_results", [])
    render_images = state.get("render_images", [])
    revision_count = state.get("revision_count", 0)

    state["revision_count"] = revision_count + 1
    threshold = getattr(Config, "QUALITY_THRESHOLD", 70.0)
    print(f"\n[validate] Round {state['revision_count']}/{state.get('max_revisions', 3)} "
          f"(threshold: {threshold})")

    # ==================================================================
    # L1：几何硬校验
    # ==================================================================
    geo_result = run_geometry_checks(cad_features, execution_results)
    geo_passed = geo_result.get("geometry_passed", False)
    geo_issues = geo_result.get("issues", [])
    print(f"[validate] L1 Geometry: {'PASS' if geo_passed else 'FAIL'}")
    for issue in geo_issues:
        print(f"  [{issue['severity']}] {issue['entity']}: {issue['description']}")

    # ==================================================================
    # L2：综合审核（视觉比对 + 语义检查，单次 LLM 调用）
    # ==================================================================
    combined_passed = False
    combined_confidence = 30.0
    combined_issues = []
    partial_validation = False

    cad_b64 = render_dxf_to_base64(cad_path) if cad_path else None
    model_b64 = None
    if render_images:
        model_b64 = _read_image_base64(render_images[0])

    if cad_b64 and model_b64:
        print("[validate] L2 Combined audit: CAD-vs-3D + semantic check...")
        try:
            combined_msg = json.dumps({
                "instruction": (
                    "Compare CAD drawing [image:0] with 3D render [image:1]. "
                    "Check visual consistency, spatial topology, and semantic "
                    "reasonableness. Do NOT repeat issues already in geometry_issues."
                ),
                "cad_features": cad_features,
                "execution_steps": [
                    {"step_id": r.get("step_id"), "operation": r.get("operation"),
                     "success": r.get("success")}
                    for r in execution_results
                ],
                "geometry_issues": geo_issues,
            }, ensure_ascii=False, indent=2)

            response = chat_with_multiple_images(
                system_prompt=VALIDATE_COMBINED_PROMPT,
                user_message=combined_msg,
                images_base64=[cad_b64, model_b64],
                max_tokens=2048,
            )
            response = response.strip()
            if response.startswith("```"):
                response = response.strip("```").strip()
                if response.startswith("json"):
                    response = response[4:].strip()

            combined_result = json.loads(response)
            combined_passed = combined_result.get("passed", False)
            combined_confidence = float(combined_result.get("confidence", 30))
            combined_issues = combined_result.get("issues", [])
            print(f"[validate] L2 Combined: {'PASS' if combined_passed else 'FAIL'} "
                  f"(confidence={combined_confidence})")
            for issue in combined_issues:
                print(f"  [{issue.get('severity', '?')}] {issue.get('entity', '?')}: "
                      f"{issue.get('description', '')}")

        except (json.JSONDecodeError, Exception) as e:
            print(f"[validate] L2 Combined audit failed: {e}")
    else:
        print(f"[validate] L2 Skipped (CAD:{bool(cad_b64)}, 3D:{bool(model_b64)})")
        partial_validation = True

    # ==================================================================
    # 质量评分与决策
    # ==================================================================
    quality = _compute_quality_score(geo_passed, combined_passed, combined_confidence)
    state["quality_score"] = quality

    all_issues = geo_issues + combined_issues
    blocking_errors = [issue for issue in geo_issues if issue.get("severity") == "error"]
    geo_hard_pass = not blocking_errors
    if partial_validation and geo_passed:
        overall_passed = True
    else:
        overall_passed = geo_hard_pass and quality >= threshold

    state["validation_result"] = {
        "overall_passed": overall_passed,
        "quality_score": quality,
        "threshold": threshold,
        "geometry_passed": geo_passed,
        "combined_passed": combined_passed,
        "combined_confidence": combined_confidence,
        "issues": all_issues,
        "blocking_errors": blocking_errors,
        "revision": state["revision_count"],
        "partial_validation": partial_validation,
    }
    state["validation_passed"] = overall_passed
    state["partial_validation"] = partial_validation

    if overall_passed:
        print(f"[validate] QUALITY {quality} >= {threshold} -- PASS")
    elif state["revision_count"] >= state.get("max_revisions", 3):
        print(f"[validate] Max revisions ({state['revision_count']}) reached, "
              f"best effort quality={quality}")
    else:
        # 关键修复：将验证问题保存为 user_feedback，plan 节点将据此重新规划
        feedback = _format_feedback(all_issues)
        state["user_confirmed"] = False
        state["user_feedback"] = feedback
        print(f"[validate] QUALITY {quality} < {threshold}, "
              f"feeding back to plan for round {state['revision_count'] + 1}")

    return state
