"""测试几何一致性检查"""

from tools.geometry_checker import run_geometry_checks, check_entity_count, check_dimensions


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
    """测试集成检查"""
    cad_features = [
        {"type": "wall", "properties": {"thickness": 240}},
        {"type": "door", "properties": {"width": 900}},
    ]
    execution_results = [
        {"step_id": 1, "success": True, "operation": "extrude_wall"},
        {"step_id": 2, "success": True, "operation": "place_door"},
    ]
    result = run_geometry_checks(cad_features, execution_results)
    assert result["geometry_passed"] is True
