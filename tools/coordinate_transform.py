"""建模坐标平移工具。

这里不做单位转换，只保证同一批建模命令和后处理范围使用同一个
模型坐标 offset。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


COORD_KEYS = ("start", "end", "location", "loc", "position")


def _params(command: Any) -> dict:
    if isinstance(command, dict):
        return command.get("params", {}) or {}
    return getattr(command, "params", {}) or {}


def _iter_points(commands: Iterable[Any]):
    for command in commands:
        params = _params(command)
        for key in COORD_KEYS:
            value = params.get(key)
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                yield value


def compute_offset(commands: list[Any]) -> tuple[float, float]:
    """从命令坐标计算左下角 offset。"""
    xs: list[float] = []
    ys: list[float] = []
    for point in _iter_points(commands):
        xs.append(float(point[0]))
        ys.append(float(point[1]))
    if not xs:
        return (0.0, 0.0)
    return (min(xs), min(ys))


def _shift_point(value: Any, offset: tuple[float, float]) -> Any:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return value
    shifted = list(value)
    shifted[0] = float(shifted[0]) - float(offset[0])
    shifted[1] = float(shifted[1]) - float(offset[1])
    return shifted


def apply_offset_to_commands(commands: list[Any], offset: tuple[float, float]) -> list[Any]:
    """返回平移后的命令副本，不修改输入。"""
    shifted = deepcopy(commands)
    for command in shifted:
        params = _params(command)
        for key in COORD_KEYS:
            if key in params:
                params[key] = _shift_point(params[key], offset)
    return shifted


def apply_offset_to_bounds(
    bounds: dict[str, Any] | None,
    offset: tuple[float, float],
) -> dict[str, Any] | None:
    """返回平移后的地面/天花板范围副本。"""
    if not bounds:
        return bounds
    shifted = dict(bounds)
    if "center" in shifted:
        shifted["center"] = _shift_point(shifted["center"], offset)
    return shifted
