"""测试 Blender 适配器的尺寸语义。"""


def test_cube_scale_uses_full_dimensions():
    from tools.background_adapter import _cube_scale_for_dimensions

    assert _cube_scale_for_dimensions(4.0, 0.24, 2.8) == (4.0, 0.24, 2.8)


def test_cube_scale_rejects_negative_dimensions():
    from tools.background_adapter import _cube_scale_for_dimensions

    try:
        _cube_scale_for_dimensions(4.0, -0.24, 2.8)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("negative dimensions must be rejected")
