"""测试 CAD 解析模块"""

from tools.cad_parser import extract_geometry, cluster_by_spatial, serialize_for_llm, infer_features_from_geometry


def test_extract_geometry_from_single_room_dxf():
    """测试从 single_room.dxf 提取几何"""
    entities = extract_geometry("examples/single_room.dxf")
    assert len(entities) > 0
    line_count = sum(1 for e in entities if e["type"] == "LINE")
    circle_count = sum(1 for e in entities if e["type"] == "CIRCLE")
    assert line_count >= 1
    assert len(entities) >= 1


def test_cluster_by_spatial_single_cluster():
    """测试小范围 DXF 聚为一个类"""
    entities = extract_geometry("examples/single_room.dxf")
    clusters = cluster_by_spatial(entities, cluster_distance=10000)
    # 所有实体应该在一个聚类中
    assert len(clusters) == 1
    assert len(clusters[0]) == len(entities)


def test_serialize_for_llm():
    """测试序列化函数输出非空"""
    entities = extract_geometry("examples/single_room.dxf")
    text = serialize_for_llm(entities)
    assert len(text) > 0
    assert "图层" in text
    assert "LINE" in text


def test_extract_geometry_file_not_found():
    """测试不存在的文件返回空"""
    entities = extract_geometry("nonexistent.dxf")
    assert entities == []


def test_extract_geometry_returns_checkpoint_serializable_numbers():
    """解析结果进入 LangGraph state 前必须只包含原生 Python 数字。"""
    entities = extract_geometry("file/2.dxf")

    for entity in entities:
        for vertex in entity.get("vertices", []):
            for value in vertex:
                assert type(value) in (int, float)


def test_infer_features_from_geometry_uses_layers():
    """图层语义应能直接兜出墙、门、窗。"""
    entities = extract_geometry("file/2.dxf")
    features = infer_features_from_geometry(entities)
    types = {feature["type"] for feature in features}

    assert "wall" in types
    assert "door" in types
    assert "window" in types
