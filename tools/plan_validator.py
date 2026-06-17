"""LLM 建模计划校验与归一化。"""

from __future__ import annotations

import math
from typing import Any


ALLOWED_OPERATIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "extrude_wall": {"required": ("start", "end")},
    "boolean_cut": {"required": ("target_wall_id", "location", "dimensions")},
    "create_column": {"required": ("location",)},
    "place_door": {"required": ("location", "width")},
    "place_window": {"required": ("location", "width")},
    "join_and_merge": {"required": ()},
    "create_floor_ceiling": {"required": ()},
    "cleanup_cutters": {"required": ()},
    "auto_camera": {"required": ()},
    "save_blend": {"required": ("filepath",)},
    "render": {"required": ("output_dir", "resolution_x", "resolution_y")},
}


def _as_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _normalize_point(value: Any, length: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) < length:
        return None
    result: list[float] = []
    for item in value[:length]:
        number = _as_number(item)
        if number is None:
            return None
        result.append(number)
    return result


def _normalize_location(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    xy = _normalize_point(value, 2)
    if xy is None:
        return None
    tail: list[float] = []
    for item in value[2:]:
        number = _as_number(item)
        if number is None:
            return None
        tail.append(number)
    return xy + tail


def _model_unit(value: Any) -> float:
    """将 CAD 语义坐标/尺寸转为米；小数值视为已经是米。"""
    number = _as_number(value)
    if number is None:
        raise ValueError(f"non-numeric value: {value}")
    if abs(number) > 50:
        return number / 1000.0
    return number


def _feature_point(point: Any) -> list[float] | None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    try:
        return [_model_unit(point[0]), _model_unit(point[1])]
    except ValueError:
        return None


def _same_segment(a_start: list[float], a_end: list[float], b_start: list[float], b_end: list[float]) -> bool:
    def close(p: list[float], q: list[float]) -> bool:
        return abs(p[0] - q[0]) < 0.05 and abs(p[1] - q[1]) < 0.05

    return (close(a_start, b_start) and close(a_end, b_end)) or (
        close(a_start, b_end) and close(a_end, b_start)
    )


def _segment_distance(point: list[float], start: list[float], end: list[float]) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length_sq))
    proj_x = sx + t * dx
    proj_y = sy + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _segment_angle(start: list[float], end: list[float]) -> float:
    return math.atan2(end[1] - start[1], end[0] - start[0])


def _wall_feature_to_step(feature: dict[str, Any], step_id: int, wall_index: int) -> dict[str, Any] | None:
    geom = feature.get("geometry", {})
    start = _feature_point(geom.get("start"))
    end = _feature_point(geom.get("end"))
    if start is None or end is None:
        vertices = geom.get("vertices", [])
        if isinstance(vertices, list) and len(vertices) >= 2:
            start = _feature_point(vertices[0])
            end = _feature_point(vertices[-1])
    if start is None or end is None:
        return None

    props = feature.get("properties", {})
    height = _model_unit(props.get("height", 2800))
    thickness = _model_unit(props.get("thickness", 240))

    return {
        "step_id": step_id,
        "operation": "extrude_wall",
        "params": {
            "wall_id": f"wall_{wall_index:02d}",
            "start": start,
            "end": end,
            "height": height,
            "thickness": thickness,
        },
        "depends_on": [],
    }


def _opening_center(feature: dict[str, Any]) -> list[float] | None:
    geom = feature.get("geometry", {})
    point = _feature_point(geom.get("center") or geom.get("location"))
    if point is not None:
        return point
    vertices = geom.get("vertices", [])
    if isinstance(vertices, list) and vertices:
        points = [_feature_point(v) for v in vertices]
        points = [p for p in points if p is not None]
        if points:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    return None


def _opening_width(feature: dict[str, Any], default: float) -> float:
    props = feature.get("properties", {})
    if props.get("width") is not None:
        return _model_unit(props["width"])
    geom = feature.get("geometry", {})
    vertices = geom.get("vertices", [])
    points = [_feature_point(v) for v in vertices] if isinstance(vertices, list) else []
    points = [p for p in points if p is not None]
    if len(points) >= 2:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return max(max(xs) - min(xs), max(ys) - min(ys), default)
    return default


def _nearest_wall_step(opening_center: list[float], wall_steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    nearest = None
    nearest_dist = float("inf")
    for step in wall_steps:
        params = step.get("params", {})
        start = _feature_point(params.get("start"))
        end = _feature_point(params.get("end"))
        if start is None or end is None:
            continue
        dist = _segment_distance(opening_center, start, end)
        if dist < nearest_dist:
            nearest = step
            nearest_dist = dist
    return nearest


def _add_opening_steps(repaired: list[dict[str, Any]], cad_features: list[dict[str, Any]], next_step_id: int) -> list[dict[str, Any]]:
    door_count = sum(1 for f in cad_features if f.get("type") == "door")
    window_count = sum(1 for f in cad_features if f.get("type") == "window")
    existing_doors = sum(1 for s in repaired if s.get("operation") == "place_door")
    existing_windows = sum(1 for s in repaired if s.get("operation") == "place_window")
    wall_steps = [s for s in repaired if s.get("operation") == "extrude_wall"]

    door_index = existing_doors + 1
    window_index = existing_windows + 1

    for feature in cad_features:
        ftype = feature.get("type")
        if ftype not in ("door", "window"):
            continue
        if ftype == "door" and existing_doors >= door_count:
            continue
        if ftype == "window" and existing_windows >= window_count:
            continue

        center = _opening_center(feature)
        if center is None:
            continue
        target_wall = _nearest_wall_step(center, wall_steps)
        if target_wall is None:
            continue
        wall_params = target_wall.get("params", {})
        wall_start = _feature_point(wall_params.get("start")) or [center[0], center[1]]
        wall_end = _feature_point(wall_params.get("end")) or [center[0] + 1.0, center[1]]
        wall_id = wall_params.get("wall_id") or f"wall_{target_wall.get('step_id', 0):02d}"
        wall_params["wall_id"] = wall_id
        wall_thickness = float(wall_params.get("thickness", 0.24))
        rotation = _segment_angle(wall_start, wall_end)

        if ftype == "door":
            width = _opening_width(feature, 0.9)
            height = _model_unit(feature.get("properties", {}).get("height", 2100))
            z = height / 2
            cut_id = next_step_id
            repaired.append({
                "step_id": cut_id,
                "operation": "boolean_cut",
                "params": {
                    "target_wall_id": wall_id,
                    "location": [center[0], center[1], z],
                    "dimensions": [width, wall_thickness * 2.0, height],
                    "rotation_z": rotation,
                    "wall_thickness": wall_thickness,
                },
                "depends_on": [target_wall.get("step_id")],
            })
            next_step_id += 1
            repaired.append({
                "step_id": next_step_id,
                "operation": "place_door",
                "params": {
                    "door_id": f"door_{door_index:02d}",
                    "location": [center[0], center[1], 0.0],
                    "width": width,
                    "height": height,
                    "rotation_z": rotation,
                    "wall_thickness": wall_thickness,
                },
                "depends_on": [cut_id],
            })
            next_step_id += 1
            existing_doors += 1
            door_index += 1
        else:
            width = _opening_width(feature, 1.2)
            props = feature.get("properties", {})
            height = _model_unit(props.get("height", 1500))
            sill = _model_unit(props.get("sill_height", 900))
            z = sill + height / 2
            cut_id = next_step_id
            repaired.append({
                "step_id": cut_id,
                "operation": "boolean_cut",
                "params": {
                    "target_wall_id": wall_id,
                    "location": [center[0], center[1], z],
                    "dimensions": [width, wall_thickness * 2.0, height],
                    "rotation_z": rotation,
                    "wall_thickness": wall_thickness,
                },
                "depends_on": [target_wall.get("step_id")],
            })
            next_step_id += 1
            repaired.append({
                "step_id": next_step_id,
                "operation": "place_window",
                "params": {
                    "window_id": f"window_{window_index:02d}",
                    "location": [center[0], center[1], 0.0],
                    "width": width,
                    "height": height,
                    "sill_height": sill,
                    "rotation_z": rotation,
                    "wall_thickness": wall_thickness,
                },
                "depends_on": [cut_id],
            })
            next_step_id += 1
            existing_windows += 1
            window_index += 1

    return repaired


def repair_plan_from_features(plan: list[dict[str, Any]], cad_features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用 CAD wall features 确定性补齐缺失的 extrude_wall 操作。"""
    repaired = [dict(step) for step in plan]
    existing_segments: list[tuple[list[float], list[float]]] = []

    for step in repaired:
        if step.get("operation") != "extrude_wall":
            continue
        params = step.get("params", {})
        start = _feature_point(params.get("start"))
        end = _feature_point(params.get("end"))
        if start is not None and end is not None:
            params["start"] = start
            params["end"] = end
            params.setdefault("wall_id", f"wall_{len(existing_segments) + 1:02d}")
            existing_segments.append((start, end))

    next_step_id = max([int(step.get("step_id", 0)) for step in repaired] or [0]) + 1
    wall_index = len(existing_segments) + 1

    for feature in cad_features:
        if feature.get("type") != "wall":
            continue
        candidate = _wall_feature_to_step(feature, next_step_id, wall_index)
        if candidate is None:
            continue
        c_start = candidate["params"]["start"]
        c_end = candidate["params"]["end"]
        if any(_same_segment(c_start, c_end, s, e) for s, e in existing_segments):
            continue
        repaired.append(candidate)
        existing_segments.append((c_start, c_end))
        next_step_id += 1
        wall_index += 1

    return _add_opening_steps(repaired, cad_features, next_step_id)


def _normalize_params(operation: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    normalized = dict(params)

    for key in ("start", "end"):
        if key in normalized:
            point = _normalize_point(normalized[key], 2)
            if point is None:
                errors.append(f"{operation}.{key} must be a numeric [x, y]")
            else:
                normalized[key] = point

    if "location" in normalized:
        point = _normalize_location(normalized["location"])
        if point is None:
            errors.append(f"{operation}.location must be numeric")
        else:
            normalized["location"] = point

    for key in ("width", "height", "thickness", "radius", "depth", "sill_height", "merge_threshold"):
        if key in normalized:
            number = _as_number(normalized[key])
            if number is None:
                errors.append(f"{operation}.{key} must be numeric")
            else:
                normalized[key] = number

    for key in ("resolution_x", "resolution_y"):
        if key in normalized:
            number = _as_number(normalized[key])
            if number is None:
                errors.append(f"{operation}.{key} must be numeric")
            else:
                normalized[key] = int(number)

    if "depends_on" in normalized and not isinstance(normalized["depends_on"], list):
        errors.append(f"{operation}.depends_on must be a list")

    return normalized, errors


def validate_plan(plan: Any, cad_features: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    normalized: list[dict[str, Any]] = []
    seen_step_ids: set[int] = set()

    if not isinstance(plan, list):
        return {"valid": False, "plan": [], "errors": ["plan must be a list"], "warnings": []}

    for index, step in enumerate(plan, start=1):
        if not isinstance(step, dict):
            errors.append(f"step {index} must be an object")
            continue

        operation = step.get("operation")
        if operation not in ALLOWED_OPERATIONS:
            errors.append(f"unsupported operation: {operation}")
            continue

        params = dict(step.get("params") or {})
        for required in ALLOWED_OPERATIONS[operation]["required"]:
            if required not in params:
                errors.append(f"{operation} missing required param: {required}")

        normalized_params, param_errors = _normalize_params(operation, params)
        errors.extend(param_errors)

        step_id = step.get("step_id", index)
        if not isinstance(step_id, int):
            errors.append(f"{operation}.step_id must be an integer")
            step_id = index
        if step_id in seen_step_ids:
            errors.append(f"duplicate step_id: {step_id}")
        seen_step_ids.add(step_id)

        depends_on = step.get("depends_on", [])
        if not isinstance(depends_on, list):
            errors.append(f"{operation}.depends_on must be a list")
            depends_on = []

        normalized.append(
            {
                "step_id": step_id,
                "operation": operation,
                "params": normalized_params,
                "depends_on": depends_on,
            }
        )

    features = cad_features or []
    wall_feature_count = sum(1 for feature in features if feature.get("type") == "wall")
    extrude_wall_count = sum(1 for step in normalized if step.get("operation") == "extrude_wall")
    if wall_feature_count and extrude_wall_count < wall_feature_count:
        errors.append(
            f"wall features require at least {wall_feature_count} extrude_wall steps, got {extrude_wall_count}"
        )
    requires_opening = any(f.get("type") in ("door", "window") for f in features)
    has_cut = any(step.get("operation") == "boolean_cut" for step in normalized)
    if requires_opening and not has_cut:
        errors.append("door/window features require at least one boolean_cut")

    valid = not errors
    return {
        "valid": valid,
        "plan": normalized if valid else [],
        "errors": errors,
        "warnings": warnings,
    }
