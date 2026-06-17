"""测试 Blender 场景摘要与墙体连通性检查。"""


def test_scene_summary_detects_disconnected_wall_components():
    from tools.scene_summary import summarize_mesh_components

    summary = summarize_mesh_components({
        "objects": [
            {"name": "wall_01", "type": "MESH", "component_count": 5},
            {"name": "door_01", "type": "MESH", "component_count": 1},
        ]
    })

    assert summary["wall_component_errors"] == ["wall_01 has 5 disconnected components"]


def test_scene_summary_keeps_non_wall_objects_as_metadata():
    from tools.scene_summary import summarize_mesh_components

    summary = summarize_mesh_components({
        "objects": [
            {"name": "wall_01", "type": "MESH", "component_count": 1},
            {"name": "window_01", "type": "MESH", "component_count": 1},
        ]
    })

    assert summary["wall_component_errors"] == []
    assert summary["object_count"] == 2
