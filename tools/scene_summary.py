"""Blender 场景摘要的 Python 侧检查工具。"""

from __future__ import annotations

from typing import Any


def summarize_mesh_components(scene_summary: dict[str, Any]) -> dict[str, Any]:
    """检查墙体 mesh 是否包含多个不连通分量。"""
    objects = scene_summary.get("objects", [])
    errors: list[str] = []

    for obj in objects:
        name = str(obj.get("name", ""))
        if not name.startswith("wall"):
            continue
        component_count = int(obj.get("component_count", 1))
        if component_count > 1:
            errors.append(f"{name} has {component_count} disconnected components")

    return {
        "object_count": len(objects),
        "wall_component_errors": errors,
    }
