"""测试几何一致性检查"""

from tools.geometry_checker import (
    run_geometry_checks,
    check_entity_count,
    check_dimensions,
    check_wall_closure,
    check_floor_ceiling,
)


def test_check_entity_count_matching():
    """测试实体数量匹配通过"""
    cad_features = [
        {"type": "wall", "properties": {"thickness": 240}},
        {"type": "wall", "properties": {"thickness": 240}},
        {"type": "door", "properties": {"width": 900}},
    ]
    execution_results = [
        {"step_id": 1, "success": True, "operation": "extrude_wall"},
        {"step_id": 2, "success": True, "operation": "extrude_wall"},
        {"step_id": 3, "success": True, "operation": "place_door"},
    ]
    result = check_entity_count(cad_features, execution_results)
    assert result["passed"] is True
    assert len(result["issues"]) == 0


def test_check_entity_count_missing_wall():
    """测试缺少墙体时报错"""
    cad_features = [
        {"type": "wall", "properties": {"thickness": 240}},
        {"type": "wall", "properties": {"thickness": 240}},
    ]
    execution_results = [
        {"step_id": 1, "success": True, "operation": "extrude_wall"},
    ]
    result = check_entity_count(cad_features, execution_results)
    assert result["passed"] is False
    assert len(result["issues"]) == 1
    assert "墙体数量不足" in result["issues"][0]["description"]


def test_check_dimensions_wall_too_thin():
    """测试墙体过薄发出警告"""
    cad_features = [
        {"type": "wall", "properties": {"thickness": 50}},  # 50mm 太薄
    ]
    execution_results = []
    result = check_dimensions(cad_features, execution_results)
    assert result["passed"] is False
    assert len(result["issues"]) == 1


def test_check_dimensions_reasonable():
    """测试合理尺寸通过检查"""
    cad_features = [
        {"type": "wall", "properties": {"thickness": 240}},
        {"type": "door", "properties": {"width": 900}},
        {"type": "window", "properties": {"width": 1500}},
    ]
    execution_results = []
    result = check_dimensions(cad_features, execution_results)
    assert result["passed"] is True


def test_run_geometry_checks_integration():
    """测试集成检查 — 4面墙围成闭合矩形"""
    cad_features = [
        # 矩形房间：4面墙首尾相连，形成闭合
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}, "properties": {"thickness": 240}},
        {"type": "wall", "geometry": {"start": [4000, 0], "end": [4000, 3000]}, "properties": {"thickness": 240}},
        {"type": "wall", "geometry": {"start": [4000, 3000], "end": [0, 3000]}, "properties": {"thickness": 240}},
        {"type": "wall", "geometry": {"start": [0, 3000], "end": [0, 0]}, "properties": {"thickness": 240}},
        {"type": "door", "properties": {"width": 900}},
    ]
    execution_results = [
        {"step_id": 1, "success": True, "operation": "extrude_wall"},
        {"step_id": 2, "success": True, "operation": "extrude_wall"},
        {"step_id": 3, "success": True, "operation": "extrude_wall"},
        {"step_id": 4, "success": True, "operation": "extrude_wall"},
        {"step_id": 5, "success": True, "operation": "join_and_merge"},
        {"step_id": 6, "success": True, "operation": "create_floor_ceiling"},
        {"step_id": 7, "success": True, "operation": "place_door"},
    ]
    result = run_geometry_checks(cad_features, execution_results)
    assert result["geometry_passed"] is True


def test_check_wall_closure_closed_rectangle():
    """4面墙闭合矩形 — 通过"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}},
        {"type": "wall", "geometry": {"start": [4000, 0], "end": [4000, 3000]}},
        {"type": "wall", "geometry": {"start": [4000, 3000], "end": [0, 3000]}},
        {"type": "wall", "geometry": {"start": [0, 3000], "end": [0, 0]}},
    ]
    result = check_wall_closure(features, tolerance_m=0.5)
    assert result["passed"] is True


def test_check_wall_closure_dangling_endpoint():
    """2面墙 L 形 — 有悬空端点，应报错"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [4000, 0]}},
        {"type": "wall", "geometry": {"start": [4000, 0], "end": [4000, 3000]}},
    ]
    result = check_wall_closure(features, tolerance_m=0.5)
    assert result["passed"] is False
    assert len(result["issues"]) == 2  # 两端各一个悬空端点


def test_check_wall_closure_isolated_walls():
    """两面孤立墙体 — 4个悬空端点"""
    features = [
        {"type": "wall", "geometry": {"start": [0, 0], "end": [3000, 0]}},
        {"type": "wall", "geometry": {"start": [10000, 0], "end": [13000, 0]}},
    ]
    result = check_wall_closure(features, tolerance_m=0.5)
    assert result["passed"] is False
    assert len(result["issues"]) == 4


def test_check_floor_ceiling_present():
    """后处理包含 floor/ceiling — 通过"""
    results = [
        {"operation": "extrude_wall"},
        {"operation": "join_and_merge"},
        {"operation": "create_floor_ceiling"},
    ]
    r = check_floor_ceiling(results)
    assert r["passed"] is True


def test_check_floor_ceiling_missing():
    """后处理缺少 floor/ceiling — 报警"""
    results = [
        {"operation": "extrude_wall"},
        {"operation": "corner_snap"},  # 旧版操作，无 join_and_merge
    ]
    r = check_floor_ceiling(results)
    assert r["passed"] is False
    assert len(r["issues"]) == 2
