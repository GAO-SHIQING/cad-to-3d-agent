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


def check_wall_closure(
    cad_features: List[Dict[str, Any]],
    tolerance_m: float = 0.5,
) -> Dict[str, Any]:
    """
    检查墙体是否形成闭合空间。
    判断标准：墙体端点是否成对靠近（每个交点至少2个端点）。
    排除门窗洞口两侧的墙体间隙（洞口间隙是建模常态，非错误）。
    """
    import math

    walls = [f for f in cad_features if f.get("type") == "wall"]
    door_windows = [f for f in cad_features if f.get("type") in ("door", "window")]

    if len(walls) < 2:
        return {
            "check": "wall_closure",
            "passed": True,
            "issues": [],
        }

    # 提取门窗位置（米制），用于判断间隙是否为洞口
    opening_infos = []
    for dw in door_windows:
        geom = dw.get("geometry", {})
        props = dw.get("properties", {})
        # door/window 可能在 geometry.center、geometry.location 或 vertices 中
        pos = geom.get("center") or geom.get("location")
        if not pos and geom.get("vertices"):
            verts = geom.get("vertices")
            xs = [float(v[0]) for v in verts if isinstance(v, (list, tuple)) and len(v) >= 2]
            ys = [float(v[1]) for v in verts if isinstance(v, (list, tuple)) and len(v) >= 2]
            if xs and ys:
                pos = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
        if pos and len(pos) >= 2:
            width_mm = props.get("width")
            if width_mm is None and geom.get("vertices"):
                verts = geom.get("vertices")
                xs = [float(v[0]) for v in verts if isinstance(v, (list, tuple)) and len(v) >= 2]
                ys = [float(v[1]) for v in verts if isinstance(v, (list, tuple)) and len(v) >= 2]
                if xs and ys:
                    width_mm = max(max(xs) - min(xs), max(ys) - min(ys))
            width_m = float(width_mm) / 1000 if width_mm is not None else 1.5
            allowed_gap_m = max(1.5, width_m * 1.1 + 0.1)
            opening_infos.append((float(pos[0]) / 1000, float(pos[1]) / 1000, allowed_gap_m))

    def _is_near_opening(x1, y1, x2, y2) -> bool:
        """检查两点之间的间隙是否包含门窗洞口"""
        gap = math.hypot(x2 - x1, y2 - y1)
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        for ox, oy, allowed_gap_m in opening_infos:
            if gap > allowed_gap_m:
                continue
            dist_to_mid = math.hypot(ox - mid_x, oy - mid_y)
            if dist_to_mid < max(gap * 0.8, 0.25):  # 门窗在间隙内
                return True
        return False

    # 收集所有端点（米制）
    endpoints = []
    for i, w in enumerate(walls):
        geom = w.get("geometry", {})
        for key in ("start", "end"):
            pt = geom.get(key)
            if pt and len(pt) >= 2:
                endpoints.append((i, key, float(pt[0]) / 1000, float(pt[1]) / 1000))

    # 统计每个端点附近有多少其他端点
    issues = []
    for i, key, x, y in endpoints:
        neighbor_count = 0
        nearest_other = None  # (jx, jy, dist)
        for j, jkey, jx, jy in endpoints:
            if i == j and key == jkey:
                continue
            dist = math.hypot(x - jx, y - jy)
            if dist <= tolerance_m:
                neighbor_count += 1
            elif nearest_other is None or dist < nearest_other[2]:
                nearest_other = (jx, jy, dist)

        if neighbor_count == 0:
            # 检查是否为门窗洞口间隙
            skip = False
            if nearest_other and opening_infos:
                skip = _is_near_opening(x, y, nearest_other[0], nearest_other[1])

            if not skip:
                issues.append({
                    "severity": "error",
                    "entity": f"wall_{i}",
                    "description": f"墙体 wall_{i} 的 {key} 端点 ({x:.2f},{y:.2f}) 悬空"
                                   f"，未连接到任何其他墙体",
                    "suggestion": f"检查墙{i}的{key}坐标，使其与相邻墙体端点对齐",
                })

    return {
        "check": "wall_closure",
        "passed": len(issues) == 0,
        "issues": issues,
    }


def check_floor_ceiling(
    execution_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    检查是否生成了地面和天花板。
    """
    operations = [r.get("operation", "") for r in execution_results]
    has_floor_ceiling = "create_floor_ceiling" in operations
    has_join_merge = "join_and_merge" in operations

    issues = []
    if not has_join_merge:
        issues.append({
            "severity": "warning",
            "entity": "walls",
            "description": "墙体未执行网格合并 (join_and_merge)，可能存在缝隙",
            "suggestion": "确保后处理管线包含 join_and_merge 步骤",
        })
    if not has_floor_ceiling:
        issues.append({
            "severity": "warning",
            "entity": "floor/ceiling",
            "description": "未生成地面和天花板",
            "suggestion": "确保后处理管线包含 create_floor_ceiling 步骤",
        })

    return {
        "check": "floor_ceiling",
        "passed": len(issues) == 0,
        "issues": issues,
    }


def check_scene_wall_components(scene_summary: Dict[str, Any]) -> Dict[str, Any]:
    """检查墙体对象是否合理合并。"""
    wall_objects = [obj for obj in scene_summary.get("objects", []) if str(obj.get("name", "")).startswith("wall")]
    issues = []

    if len(wall_objects) > 1:
        issues.append({
            "severity": "error",
            "entity": "walls",
            "description": f"墙体仍然拆成 {len(wall_objects)} 个对象，未完成合并",
            "suggestion": "检查 join_and_merge 是否生效，以及墙体命名是否统一",
        })
    elif wall_objects:
        obj = wall_objects[0]
        count = int(obj.get("component_count", 1))
        if count > 1:
            issues.append({
                "severity": "warning",
                "entity": obj.get("name", "wall"),
                "description": f"墙体网格包含 {count} 个不连通分量，但已合并为单个对象",
                "suggestion": "如视觉上仍有裂缝，可继续检查端点对齐和 remove_doubles 阈值",
            })

    return {
        "check": "scene_wall_components",
        "passed": not any(issue.get("severity") == "error" for issue in issues),
        "issues": issues,
    }


def run_geometry_checks(
    cad_features: List[Dict[str, Any]],
    execution_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """运行所有几何检查，返回汇总报告"""
    scene_summary = None
    for result in execution_results:
        output = result.get("output", {}) if isinstance(result, dict) else {}
        if isinstance(output, dict) and output.get("scene_summary"):
            scene_summary = output["scene_summary"]
            break

    checks = [
        check_entity_count(cad_features, execution_results),
        check_dimensions(cad_features, execution_results),
        check_wall_closure(cad_features),
        check_floor_ceiling(execution_results),
    ]

    if scene_summary:
        checks.append(check_scene_wall_components(scene_summary))

    all_issues = []
    for check in checks:
        all_issues.extend(check.get("issues", []))

    passed = all(c.get("passed", False) for c in checks)

    return {
        "geometry_passed": passed,
        "checks": checks,
        "issues": all_issues,
        "blocking_errors": [issue for issue in all_issues if issue.get("severity") == "error"],
        "warnings": [issue for issue in all_issues if issue.get("severity") == "warning"],
    }
