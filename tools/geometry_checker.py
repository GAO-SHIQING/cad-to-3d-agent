"""几何一致性验证 — 确定性检查（非 LLM）"""

from typing import List, Dict, Any


def check_entity_count(
    cad_features: List[Dict[str, Any]],
    execution_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    检查建模实体数量是否与 DXF 解析结果一致。
    返回 {passed, details}。
    """
    expected: Dict[str, int] = {}
    for f in cad_features:
        ftype = f.get("type", "unknown")
        expected[ftype] = expected.get(ftype, 0) + 1

    actual: Dict[str, int] = {}
    for r in execution_results:
        if not r.get("success"):
            continue
        op = r.get("operation") or (r.get("output") or {}).get("type", "unknown")
        actual[op] = actual.get(op, 0) + 1

    issues = []
    # 检查墙体数量
    if expected.get("wall", 0) > 0:
        wall_ops = actual.get("extrude_wall", 0)
        expected_walls = expected.get("wall", 0)
        if wall_ops < expected_walls:
            issues.append({
                "severity": "error",
                "entity": "wall",
                "description": f"墙体数量不足: 期望 {expected_walls}，实际 {wall_ops}",
                "suggestion": f"检查是否遗漏了 {expected_walls - wall_ops} 面墙",
            })

    # 检查门窗
    for entity_type, op_name in [("door", "place_door"), ("window", "place_window")]:
        expected_count = expected.get(entity_type, 0)
        actual_count = actual.get(op_name, 0)
        if expected_count > 0 and actual_count < expected_count:
            issues.append({
                "severity": "error",
                "entity": entity_type,
                "description": f"{entity_type} 数量不足: 期望 {expected_count}，实际 {actual_count}",
                "suggestion": f"添加缺失的 {expected_count - actual_count} 个 {entity_type}",
            })

    return {
        "check": "entity_count",
        "passed": len(issues) == 0,
        "issues": issues,
    }


def check_dimensions(
    cad_features: List[Dict[str, Any]],
    execution_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    检查关键尺寸是否在合理范围内。
    """
    issues = []
    WALL_THICKNESS_MIN = 0.1  # 最小墙厚（米）
    WALL_THICKNESS_MAX = 0.5  # 最大墙厚（米）
    DOOR_WIDTH_MIN = 0.6
    DOOR_WIDTH_MAX = 1.5
    WINDOW_WIDTH_MIN = 0.5
    WINDOW_WIDTH_MAX = 4.0

    for feature in cad_features:
        ftype = feature.get("type", "")
        props = feature.get("properties", {})

        if ftype == "wall":
            thickness_mm = props.get("thickness", 240)
            thickness_m = thickness_mm / 1000
            if thickness_m < WALL_THICKNESS_MIN or thickness_m > WALL_THICKNESS_MAX:
                issues.append({
                    "severity": "warning",
                    "entity": "wall",
                    "description": f"墙体厚度 {thickness_m:.3f}m 超出合理范围",
                    "suggestion": f"建议厚度在 {WALL_THICKNESS_MIN}-{WALL_THICKNESS_MAX}m",
                })

        elif ftype == "door":
            width_mm = props.get("width", 900)
            width_m = width_mm / 1000
            if width_m < DOOR_WIDTH_MIN or width_m > DOOR_WIDTH_MAX:
                issues.append({
                    "severity": "warning",
                    "entity": "door",
                    "description": f"门宽 {width_m:.2f}m 超出合理范围",
                    "suggestion": f"建议门宽在 {DOOR_WIDTH_MIN}-{DOOR_WIDTH_MAX}m",
                })

        elif ftype == "window":
            width_mm = props.get("width", 1500)
            width_m = width_mm / 1000
            if width_m < WINDOW_WIDTH_MIN or width_m > WINDOW_WIDTH_MAX:
                issues.append({
                    "severity": "warning",
                    "entity": "window",
                    "description": f"窗宽 {width_m:.2f}m 超出合理范围",
                    "suggestion": f"建议窗宽在 {WINDOW_WIDTH_MIN}-{WINDOW_WIDTH_MAX}m",
                })

    return {
        "check": "dimensions",
        "passed": len(issues) == 0,
        "issues": issues,
    }


def run_geometry_checks(
    cad_features: List[Dict[str, Any]],
    execution_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """运行所有几何检查，返回汇总报告"""
    checks = [
        check_entity_count(cad_features, execution_results),
        check_dimensions(cad_features, execution_results),
    ]

    all_issues = []
    for check in checks:
        all_issues.extend(check.get("issues", []))

    passed = all(c.get("passed", False) for c in checks)

    return {
        "geometry_passed": passed,
        "checks": checks,
        "issues": all_issues,
    }
