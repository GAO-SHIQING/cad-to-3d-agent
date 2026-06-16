"""墙体拓扑推断 — 端点聚类 + 地板/天花板范围计算

解决问题：
1. Vision LLM 提取的墙体端点坐标存在误差，导致本应相交的墙体不闭合
2. 通过空间聚类将相近端点归并为共享角点，统一坐标
"""

import math
from typing import List, Dict, Any, Tuple, Optional


def cluster_wall_endpoints(
    cad_features: List[Dict[str, Any]],
    tolerance_mm: float = 800.0,
) -> List[Dict[str, Any]]:
    """
    对墙体端点进行空间聚类，将相近端点归并为共享角点。

    算法：
    1. 提取所有类型为 'wall' 的实体的 start/end 点
    2. 贪心聚类：端点间距 < tolerance_mm 的归入同一簇
    3. 每簇计算几何中心，所有属于该簇的端点统一为同一坐标
    4. 返回修正后的 cad_features（保持顺序不变）

    这样保证本应相交的墙体共享完全一致的角点坐标，
    后续 plan 节点基于修正坐标生成建模计划，从根本上消除对齐误差。
    """
    # 收集墙体在原始列表中的位置
    wall_indices = [i for i, f in enumerate(cad_features) if f.get("type") == "wall"]
    if len(wall_indices) < 2:
        return cad_features

    # 收集所有端点，tag 中记录 (cad_features 原始索引, "start"|"end", 坐标)
    endpoints: List[Tuple[int, str, Tuple[float, float]]] = []
    for idx in wall_indices:
        geom = cad_features[idx].get("geometry", {})
        start = geom.get("start")
        end = geom.get("end")
        if start and len(start) >= 2:
            endpoints.append((idx, "start", (float(start[0]), float(start[1]))))
        if end and len(end) >= 2:
            endpoints.append((idx, "end", (float(end[0]), float(end[1]))))

    # 贪心聚类
    clusters: List[List[Tuple[int, str, Tuple[float, float]]]] = []
    remaining = list(endpoints)

    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        i = 0
        while i < len(remaining):
            ep = remaining[i]
            matched = False
            for member in cluster:
                dx = ep[2][0] - member[2][0]
                dy = ep[2][1] - member[2][1]
                if math.hypot(dx, dy) < tolerance_mm:
                    cluster.append(remaining.pop(i))
                    matched = True
                    break
            if not matched:
                i += 1
        clusters.append(cluster)

    # 为每个包含 ≥2 个端点的簇计算质心 → 修正映射
    # corrections: {cad_features_index: {"start": [x,y] | None, "end": [x,y] | None}}
    corrections: Dict[int, Dict[str, Optional[List[float]]]] = {}

    for cluster in clusters:
        if len(cluster) < 2:
            continue  # 孤立端点保留原始坐标

        cx = sum(ep[2][0] for ep in cluster) / len(cluster)
        cy = sum(ep[2][1] for ep in cluster) / len(cluster)

        for idx, key, _orig in cluster:
            if idx not in corrections:
                corrections[idx] = {"start": None, "end": None}
            corrections[idx][key] = [cx, cy]

    # 构造修正后的列表（浅拷贝 + 坐标修正）
    result = []
    for i, feat in enumerate(cad_features):
        f = dict(feat)
        if i in corrections:
            corr = corrections[i]
            geom = dict(f.get("geometry", {}))
            if corr["start"] is not None:
                geom["start"] = corr["start"]
            if corr["end"] is not None:
                geom["end"] = corr["end"]
            f["geometry"] = geom
        result.append(f)

    connected_corners = sum(1 for c in clusters if len(c) >= 2)
    snapped_walls = len(corrections)
    if connected_corners > 0:
        print(f"[wall_topology] 发现 {connected_corners} 个连接角点，"
              f"修正了 {snapped_walls} 段墙体的端点坐标 "
              f"(tolerance={tolerance_mm:.0f}mm)")

    return result


def infer_floor_bounds(
    cad_features: List[Dict[str, Any]],
    margin_m: float = 0.3,
) -> Optional[Dict[str, Any]]:
    """
    从墙体布局推断地板/天花板范围（用于后处理自动生成）。

    返回:
        {
            "center": [cx, cy],       # 米制
            "size": [sx, sy],          # 米制
            "wall_height": 2.8,        # 米制
        }
        或 None（无墙体时）
    """
    walls = [f for f in cad_features if f.get("type") == "wall"]
    if not walls:
        return None

    all_x, all_y = [], []
    for wall in walls:
        geom = wall.get("geometry", {})
        for key in ("start", "end"):
            pt = geom.get(key)
            if pt and len(pt) >= 2:
                all_x.append(float(pt[0]) / 1000.0)  # mm → m
                all_y.append(float(pt[1]) / 1000.0)

    # 也纳入柱体位置
    for feat in cad_features:
        if feat.get("type") == "column":
            center = feat.get("geometry", {}).get("center")
            if center and len(center) >= 2:
                all_x.append(float(center[0]) / 1000.0)
                all_y.append(float(center[1]) / 1000.0)

    if not all_x:
        return None

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    size_x = (max_x - min_x) + 2 * margin_m
    size_y = (max_y - min_y) + 2 * margin_m
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    # 推断墙高
    heights = [
        float(w.get("properties", {}).get("height", 2800)) / 1000.0
        for w in walls
        if w.get("properties", {}).get("height")
    ]
    wall_height = max(heights) if heights else 2.8

    return {
        "center": [center_x, center_y],
        "size": [max(size_x, 0.5), max(size_y, 0.5)],
        "wall_height": wall_height,
    }
