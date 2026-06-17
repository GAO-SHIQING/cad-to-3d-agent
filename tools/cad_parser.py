"""CAD 解析模块 — ezdxf 集成 + 几何提取 + LLM 序列化"""

import math
from typing import List, Dict, Any
import ezdxf


def _native_number(value: Any) -> float:
    """将 ezdxf/numpy 标量统一转成原生 float。"""
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise TypeError(f"non-numeric CAD coordinate: {value!r}")


def extract_vertices(entity: Any) -> List[List[float]]:
    """从 ezdxf 实体中提取顶点坐标列表"""
    dxftype = entity.dxftype()

    if dxftype == "LINE":
        return [
            [_native_number(entity.dxf.start.x), _native_number(entity.dxf.start.y)],
            [_native_number(entity.dxf.end.x), _native_number(entity.dxf.end.y)],
        ]

    if dxftype in ("LWPOLYLINE", "POLYLINE"):
        if dxftype == "LWPOLYLINE":
            points = entity.get_points("xy")
        else:
            points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        return [[_native_number(p[0]), _native_number(p[1])] for p in points]

    if dxftype == "ARC":
        center = entity.dxf.center
        return [[_native_number(center.x), _native_number(center.y)]]

    if dxftype == "CIRCLE":
        center = entity.dxf.center
        return [[_native_number(center.x), _native_number(center.y)]]

    if dxftype == "INSERT":
        insert = entity.dxf.insert
        return [[_native_number(insert.x), _native_number(insert.y)]]

    if dxftype in ("TEXT", "MTEXT"):
        insert = entity.dxf.insert
        return [[_native_number(insert.x), _native_number(insert.y)]]

    if dxftype == "DIMENSION":
        try:
            defpoint = entity.dxf.defpoint
            return [[_native_number(defpoint.x), _native_number(defpoint.y)]]
        except AttributeError:
            return []

    return []


def extract_properties(entity: Any) -> Dict[str, Any]:
    """从 ezdxf 实体中提取关键属性"""
    dxftype = entity.dxftype()
    props: Dict[str, Any] = {}

    # 通用属性
    try:
        props["layer"] = entity.dxf.layer
    except AttributeError:
        props["layer"] = "0"

    if dxftype == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        dx = end.x - start.x
        dy = end.y - start.y
        props["length"] = math.hypot(dx, dy)
        props["angle_deg"] = math.degrees(math.atan2(dy, dx))

    elif dxftype in ("LWPOLYLINE", "POLYLINE"):
        props["is_closed"] = bool(entity.closed)

    elif dxftype == "ARC":
        props["radius"] = entity.dxf.radius
        props["start_angle"] = entity.dxf.start_angle
        props["end_angle"] = entity.dxf.end_angle

    elif dxftype == "CIRCLE":
        props["radius"] = entity.dxf.radius

    elif dxftype in ("TEXT", "MTEXT"):
        try:
            props["text"] = entity.dxf.text
        except AttributeError:
            props["text"] = entity.plain_text() if hasattr(entity, "plain_text") else ""

    elif dxftype == "INSERT":
        try:
            props["block_name"] = entity.dxf.name
        except AttributeError:
            props["block_name"] = "unknown"
        try:
            props["scale"] = [entity.dxf.xscale, entity.dxf.yscale, entity.dxf.zscale]
        except AttributeError:
            props["scale"] = [1, 1, 1]
        try:
            props["rotation"] = entity.dxf.rotation
        except AttributeError:
            props["rotation"] = 0

    return props




def _default_opening_dimensions(layer: str, block_name: str, properties: Dict[str, Any]) -> tuple[float, float, float]:
    layer_lower = layer.lower()
    block_lower = block_name.lower()
    if "门" in layer or "door" in layer_lower or "door" in block_lower:
        width = 900.0
        height = 2100.0
        sill = 0.0
    else:
        width = 1500.0
        height = 1500.0
        sill = float(properties.get("sill_height", 900.0))
    return width, height, sill


def infer_features_from_geometry(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从原始几何和图层语义确定性推断建筑特征。"""
    features: List[Dict[str, Any]] = []
    wall_index = 1
    door_index = 1
    window_index = 1

    for entity in entities:
        layer = str(entity.get("layer", ""))
        layer_lower = layer.lower()
        ent_type = str(entity.get("type", "")).upper()
        vertices = entity.get("vertices", [])
        props = dict(entity.get("properties", {}))

        if "墙" in layer or "wall" in layer_lower:
            points = [list(v[:2]) for v in vertices if isinstance(v, (list, tuple)) and len(v) >= 2]
            if ent_type == "LINE" and len(points) >= 2:
                features.append({
                    "type": "wall",
                    "geometry": {"start": points[0], "end": points[1]},
                    "properties": props,
                })
                wall_index += 1
            elif ent_type in ("LWPOLYLINE", "POLYLINE") and len(points) >= 2:
                closed = bool(props.get("is_closed"))
                pairs = list(zip(points, points[1:]))
                if closed and len(points) >= 3:
                    pairs.append((points[-1], points[0]))
                for start, end in pairs:
                    features.append({
                        "type": "wall",
                        "geometry": {"start": [float(start[0]), float(start[1])], "end": [float(end[0]), float(end[1])]},
                        "properties": props,
                    })
                    wall_index += 1

        if ent_type == "INSERT":
            block_name = str(props.get("block_name", ""))
            center = None
            if vertices:
                first = vertices[0]
                if isinstance(first, (list, tuple)) and len(first) >= 2:
                    center = [float(first[0]), float(first[1])]
            if center is None:
                continue

            if "门" in layer or "door" in layer_lower or "door" in block_name.lower():
                width, height, sill = _default_opening_dimensions(layer, block_name, props)
                features.append({
                    "type": "door",
                    "geometry": {"center": center, "vertices": [[center[0] - width / 2, center[1]], [center[0] + width / 2, center[1]]]},
                    "properties": {"width": width, "height": height, "sill_height": sill},
                })
                door_index += 1
            elif "窗" in layer or "window" in layer_lower or "window" in block_name.lower():
                width, height, sill = _default_opening_dimensions(layer, block_name, props)
                features.append({
                    "type": "window",
                    "geometry": {"center": center, "vertices": [[center[0] - width / 2, center[1]], [center[0] + width / 2, center[1]]]},
                    "properties": {"width": width, "height": height, "sill_height": sill},
                })
                window_index += 1

    return features


def extract_geometry(dxf_path: str) -> List[Dict[str, Any]]:
    """ezdxf 读取 DXF，提取所有实体的原始几何数据"""
    try:
        doc = ezdxf.readfile(dxf_path)
    except (IOError, ezdxf.DXFStructureError):
        return []

    entities = []

    for entity in doc.modelspace():
        dxftype = entity.dxftype()
        # 跳过 HATCH（填充图案，几何意义弱）
        if dxftype == "HATCH":
            continue

        vertices = extract_vertices(entity)
        if not vertices:
            continue

        entities.append({
            "type": dxftype,
            "layer": getattr(entity.dxf, "layer", "0"),
            "vertices": vertices,
            "properties": extract_properties(entity),
        })

    return entities


def cluster_by_spatial(
    entities: List[Dict[str, Any]],
    cluster_distance: float = 5000.0,
) -> List[List[Dict[str, Any]]]:
    """
    基于坐标范围进行空间聚类，避免多层平面图混在一起。
    cluster_distance: 聚类距离阈值（毫米），默认 5000mm = 5m。
    """
    if not entities:
        return []

    def centroid(ent: Dict) -> tuple[float, float]:
        verts = ent.get("vertices", [])
        if not verts:
            return (0.0, 0.0)
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    clusters: List[List[Dict]] = []
    remaining = list(entities)

    while remaining:
        current = remaining.pop(0)
        current_centroid = centroid(current)
        cluster = [current]

        i = 0
        while i < len(remaining):
            ent = remaining[i]
            ent_centroid = centroid(ent)
            dx = ent_centroid[0] - current_centroid[0]
            dy = ent_centroid[1] - current_centroid[1]
            dist = math.hypot(dx, dy)

            if dist < cluster_distance:
                cluster.append(remaining.pop(i))
            else:
                i += 1

        clusters.append(cluster)

    return clusters


def serialize_for_llm(entities: List[Dict[str, Any]], max_entities: int = 200) -> str:
    """将几何数据序列化为 LLM 可理解的文本描述"""
    lines: List[str] = []
    lines.append(f"共 {len(entities)} 个几何实体。以下按图层分组列出：")

    # 按图层分组
    by_layer: Dict[str, List[Dict]] = {}
    for e in entities:
        layer = e.get("layer", "0")
        by_layer.setdefault(layer, []).append(e)

    for layer, layer_entities in by_layer.items():
        lines.append(f"\n## 图层: {layer} ({len(layer_entities)} 个实体)")
        for i, e in enumerate(layer_entities[:max_entities]):
            ent_type = e.get("type", "?")
            verts = e.get("vertices", [])
            props = e.get("properties", {})

            verts_str = ", ".join(
                f"[{v[0]:.1f}, {v[1]:.1f}]" for v in verts
            )
            prop_str = ", ".join(f"{k}={v}" for k, v in props.items())

            lines.append(
                f"  [{i}] {ent_type} | vertices=[{verts_str}]"
                + (f" | {prop_str}" if prop_str else "")
            )

        if len(layer_entities) > max_entities:
            lines.append(f"  ... 还有 {len(layer_entities) - max_entities} 个实体未列出")

    return "\n".join(lines)
