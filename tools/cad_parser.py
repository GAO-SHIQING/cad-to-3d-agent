"""CAD 解析模块 — ezdxf 集成 + 几何提取 + LLM 序列化"""

import math
from typing import List, Dict, Any
import ezdxf


def extract_vertices(entity: Any) -> List[List[float]]:
    """从 ezdxf 实体中提取顶点坐标列表"""
    dxftype = entity.dxftype()

    if dxftype == "LINE":
        return [
            [entity.dxf.start.x, entity.dxf.start.y],
            [entity.dxf.end.x, entity.dxf.end.y],
        ]

    if dxftype in ("LWPOLYLINE", "POLYLINE"):
        if dxftype == "LWPOLYLINE":
            points = entity.get_points("xy")
        else:
            points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        return [[p[0], p[1]] for p in points]

    if dxftype == "ARC":
        center = entity.dxf.center
        return [[center.x, center.y]]

    if dxftype == "CIRCLE":
        center = entity.dxf.center
        return [[center.x, center.y]]

    if dxftype == "INSERT":
        insert = entity.dxf.insert
        return [[insert.x, insert.y]]

    if dxftype in ("TEXT", "MTEXT"):
        insert = entity.dxf.insert
        return [[insert.x, insert.y]]

    if dxftype == "DIMENSION":
        try:
            defpoint = entity.dxf.defpoint
            return [[defpoint.x, defpoint.y]]
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
