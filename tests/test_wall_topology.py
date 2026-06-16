"""wall_topology 模块测试 — 端点聚类 + 地板范围推断"""

from tools.wall_topology import cluster_wall_endpoints, infer_floor_bounds


def test_cluster_wall_endpoints_no_walls():
    """没有墙体时，返回原列表"""
    features = [
        {"type": "door", "properties": {"width": 900}},
    ]
    result = cluster_wall_endpoints(features)
    assert len(result) == 1
    assert result[0]["type"] == "door"


def test_cluster_wall_endpoints_single_wall():
    """只有一面墙，不需要修正"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [3000, 0]}},
    ]
    result = cluster_wall_endpoints(features)
    assert result[0]["geometry"]["start"] == [0, 0]
    assert result[0]["geometry"]["end"] == [3000, 0]


def test_cluster_wall_endpoints_two_connected_walls():
    """两面相交墙体 — 端点应归为统一坐标"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [3000, 0]}},
        # wall_01 的 start 与 wall_00 的 end 接近（故意偏移 200mm 模拟 LLM 误差）
        {"type": "wall", "geometry": {"start": [3020, 20], "end": [3020, 4000]}},
    ]
    result = cluster_wall_endpoints(features, tolerance_mm=500)

    # 两个墙的相交端点应该被修正为簇质心
    w0_end = result[0]["geometry"]["end"]      # 原 [3000, 0]
    w1_start = result[1]["geometry"]["start"]  # 原 [3020, 20]
    # 质心 = ([3000+3020]/2, [0+20]/2) = (3010, 10)
    assert w0_end == [3010.0, 10.0]
    assert w1_start == [3010.0, 10.0]


def test_cluster_wall_endpoints_far_walls():
    """两面相距很远的墙体 — 不应被合并"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [3000, 0]}},
        {"type": "wall", "geometry": {"start": [10000, 0], "end": [13000, 0]}},
    ]
    result = cluster_wall_endpoints(features, tolerance_mm=800)
    # 端点距离 7000mm >> 800mm，不应修正
    assert result[0]["geometry"]["end"] == [3000, 0]
    assert result[1]["geometry"]["start"] == [10000, 0]


def test_cluster_wall_endpoints_three_walls_corner():
    """三面墙汇于同一角点"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [3000, 0]}},
        {"type": "wall", "geometry": {"start": [3010, -10], "end": [3010, 4000]}},
        {"type": "wall", "geometry": {"start": [2990, 10], "end": [0, 4000]}},
    ]
    result = cluster_wall_endpoints(features, tolerance_mm=500)
    # 三个端点 (3000,0), (3010,-10), (2990,10) 应归为同一簇
    # 质心 = ((3000+3010+2990)/3, (0-10+10)/3) = (3000, 0)
    w0_end = result[0]["geometry"]["end"]
    w1_start = result[1]["geometry"]["start"]
    w2_start = result[2]["geometry"]["start"]
    assert w0_end == [3000.0, 0.0]
    assert w1_start == [3000.0, 0.0]
    assert w2_start == [3000.0, 0.0]


def test_cluster_preserves_non_wall_entities():
    """非墙体实体不受影响"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [3000, 0]}},
        {"type": "door", "geometry": {"center": [1500, 100]}, "properties": {"width": 900}},
        {"type": "wall", "geometry": {"start": [3010, 0], "end": [3010, 4000]}},
        {"type": "column", "geometry": {"center": [0, 0], "radius": 100}},
    ]
    result = cluster_wall_endpoints(features, tolerance_mm=500)
    assert result[1]["type"] == "door"
    assert result[1]["properties"]["width"] == 900
    assert result[3]["type"] == "column"


def test_infer_floor_bounds_rectangle():
    """矩形房间 — 地板范围正确"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}, "properties": {"height": 2800}},
        {"type": "wall", "geometry": {"start": [4000, 0], "end": [4000, 3000]}},
        {"type": "wall", "geometry": {"start": [4000, 3000], "end": [0, 3000]}},
        {"type": "wall", "geometry": {"start": [0, 3000], "end": [0, 0]}},
    ]
    bounds = infer_floor_bounds(features, margin_m=0.3)
    assert bounds is not None
    # 范围: 0~4m × 0~3m，加上 0.3m margin
    assert bounds["center"] == [2.0, 1.5]
    assert bounds["size"] == [4.6, 3.6]
    assert bounds["wall_height"] == 2.8


def test_infer_floor_bounds_no_walls():
    """无墙体 — 返回 None"""
    features = [{"type": "door"}]
    assert infer_floor_bounds(features) is None
