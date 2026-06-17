"""测试 DXF 渲染缓存。"""

import io


class FakeFigure:
    def __init__(self):
        self.savefig_calls = 0

    def savefig(self, buf, *args, **kwargs):
        self.savefig_calls += 1
        buf.write(b"fake-png")


def test_render_dxf_to_base64_reuses_cached_png_bytes(monkeypatch, tmp_path):
    from tools import dxf_viewer

    dxf_path = tmp_path / "room.dxf"
    dxf_path.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")
    fig = FakeFigure()

    monkeypatch.setattr(dxf_viewer, "_render_core", lambda *args, **kwargs: (fig, object()))
    monkeypatch.setattr(dxf_viewer.plt, "close", lambda *args, **kwargs: None)
    dxf_viewer.clear_render_cache()

    first = dxf_viewer.render_dxf_to_base64(str(dxf_path), dpi=200)
    second = dxf_viewer.render_dxf_to_base64(str(dxf_path), dpi=200)

    assert first == second
    assert fig.savefig_calls == 1


def test_render_dxf_to_png_uses_same_cached_png_bytes(monkeypatch, tmp_path):
    from tools import dxf_viewer

    dxf_path = tmp_path / "room.dxf"
    out_path = tmp_path / "out.png"
    dxf_path.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")
    fig = FakeFigure()

    monkeypatch.setattr(dxf_viewer, "_render_core", lambda *args, **kwargs: (fig, object()))
    monkeypatch.setattr(dxf_viewer, "_validate_output_path", lambda path: str(out_path))
    monkeypatch.setattr(dxf_viewer.plt, "close", lambda *args, **kwargs: None)
    dxf_viewer.clear_render_cache()

    assert dxf_viewer.render_dxf_to_base64(str(dxf_path), dpi=200)
    assert dxf_viewer.render_dxf_to_png(str(dxf_path), str(out_path), dpi=200)

    assert out_path.read_bytes() == b"fake-png"
    assert fig.savefig_calls == 1
