"""测试建模命令和后处理范围使用同一坐标平移。"""

from tools.blender_tool import BlenderCommand


def test_coordinate_transform_applies_same_offset_to_dict_commands_and_bounds():
    from tools.coordinate_transform import (
        apply_offset_to_bounds,
        apply_offset_to_commands,
        compute_offset,
    )

    commands = [
        {"operation": "extrude_wall", "params": {"start": [10.0, 20.0], "end": [14.0, 20.0]}},
    ]

    offset = compute_offset(commands)
    shifted = apply_offset_to_commands(commands, offset)
    shifted_bounds = apply_offset_to_bounds(
        {"center": [12.0, 21.5], "size": [4.6, 3.6], "wall_height": 2.8},
        offset,
    )

    assert offset == (10.0, 20.0)
    assert shifted[0]["params"]["start"] == [0.0, 0.0]
    assert shifted[0]["params"]["end"] == [4.0, 0.0]
    assert shifted_bounds["center"] == [2.0, 1.5]
    assert commands[0]["params"]["start"] == [10.0, 20.0]


def test_coordinate_transform_supports_blender_commands():
    from tools.coordinate_transform import apply_offset_to_commands, compute_offset

    commands = [
        BlenderCommand(
            operation="place_door",
            params={"location": [3.5, 4.0, 0.0], "width": 0.9},
            step_id=1,
        )
    ]

    offset = compute_offset(commands)
    shifted = apply_offset_to_commands(commands, offset)

    assert offset == (3.5, 4.0)
    assert shifted[0].params["location"] == [0.0, 0.0, 0.0]
    assert commands[0].params["location"] == [3.5, 4.0, 0.0]
