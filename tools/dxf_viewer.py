"""DXF -> PNG 渲染 -- 让 LLM "看" 图纸

基于 autocad-mcp (puran-water/autocad-mcp) 的 MatplotlibScreenshotProvider 思路，
使用 ezdxf + matplotlib 将 DXF 矢量图渲染为高可见度 PNG 位图，供视觉 LLM 分析。

渲染特性：
- 图层颜色区分 (WALL=黑, WINDOW=蓝, COLUMN=红, DOOR=绿)
- 坐标轴与网格，帮助 LLM 估计位置
- 高 DPI + 加粗线宽，确保线条清晰可辨
"""

import base64
import io
import os
from functools import lru_cache
from pathlib import Path

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Allowed directories for path safety
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ALLOWED_INPUT_DIRS = [
    _PROJECT_ROOT / "examples",
    _PROJECT_ROOT / "file",
]
_ALLOWED_OUTPUT_DIR = _PROJECT_ROOT / "output"


def _validate_input_path(path: str) -> str:
    """Resolve input DXF path and verify it is a safe .dxf file.

    Prevents traversal outside the filesystem root (e.g. /../../etc/passwd
    would be caught).  Allows any .dxf file via CLI or project directories.
    """
    resolved = Path(path).resolve()
    if not str(resolved).lower().endswith(".dxf"):
        raise ValueError(f"Input path must be a .dxf file: {path}")
    if not resolved.exists():
        raise ValueError(f"Input file does not exist: {path}")
    return str(resolved)


def _validate_output_path(path: str) -> str:
    """Resolve output path and verify it stays within the project output dir.

    Prevents writing to arbitrary system locations.
    """
    resolved = Path(path).resolve()
    allowed = _ALLOWED_OUTPUT_DIR.resolve()
    if resolved == allowed or str(resolved).startswith(str(allowed) + os.sep):
        return str(resolved)
    raise ValueError(
        f"Output path '{path}' resolves outside allowed directory: {allowed}"
    )


# 图层渲染配置
LAYER_STYLES = {
    "WALL":   {"lineweight": 0.5, "color": "#1a1a1a"},
    "WINDOW": {"lineweight": 0.35, "color": "#2980b9"},
    "COLUMN": {"lineweight": 0.4, "color": "#c0392b"},
    "DOOR":   {"lineweight": 0.35, "color": "#27ae60"},
}
DEFAULT_STYLE = {"lineweight": 0.3, "color": "#7f8c8d"}


def clear_render_cache() -> None:
    """清空 DXF 渲染缓存，主要供测试和长进程调试使用。"""
    _render_png_bytes_cached.cache_clear()


def _cache_key(dxf_path: str, dpi: int) -> tuple[str, int, int, int]:
    resolved = Path(_validate_input_path(dxf_path)).resolve()
    stat = resolved.stat()
    return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size), int(dpi))


def _apply_layer_styles(ctx: RenderContext) -> None:
    """通过回调函数为不同图层设置线宽和颜色"""

    def override(layers):
        for props in layers:
            name = (props.layer or "").upper()
            style = DEFAULT_STYLE
            for keyword, cfg in LAYER_STYLES.items():
                if keyword in name:
                    style = cfg
                    break
            props.lineweight = style["lineweight"]
            props.color = style["color"]

    ctx.set_layer_properties_override(override)


def _render_core(
    dxf_path: str,
    dpi: int = 200,
    figsize: tuple = (14, 10),
) -> tuple[plt.Figure, plt.Axes] | None:
    """核心渲染逻辑：打开 DXF，配置 matplotlib，返回 (fig, ax)。

    失败返回 None，调用方负责 plt.close()。
    """
    try:
        _validate_input_path(dxf_path)
        doc = ezdxf.readfile(dxf_path)
    except ValueError as e:
        print(f"[dxf_viewer] 路径验证失败: {e}")
        return None
    except (IOError, ezdxf.DXFStructureError) as e:
        print(f"[dxf_viewer] 读取 DXF 失败: {e}")
        return None

    if len(doc.modelspace()) == 0:
        print("[dxf_viewer] DXF 文件为空")
        return None

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3, linestyle="--", linewidth=0.5)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title(Path(dxf_path).name, fontsize=10)

    ctx = RenderContext(doc)
    _apply_layer_styles(ctx)

    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(doc.modelspace())

    return (fig, ax)


def _render_png_bytes_from_key(
    cache_key: tuple[str, int, int, int]
) -> bytes | None:
    path, _mtime_ns, _size, dpi = cache_key
    result = _render_core(path, dpi=dpi)
    if result is None:
        return None

    fig, _ax = result
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.2)
        return buf.getvalue()
    except Exception as e:
        print(f"[dxf_viewer] 渲染失败: {e}")
        return None
    finally:
        plt.close(fig)


@lru_cache(maxsize=16)
def _render_png_bytes_cached(
    cache_key: tuple[str, int, int, int]
) -> bytes | None:
    return _render_png_bytes_from_key(cache_key)


def _render_png_bytes(dxf_path: str, dpi: int) -> bytes | None:
    try:
        key = _cache_key(dxf_path, dpi)
    except ValueError as e:
        print(f"[dxf_viewer] 路径验证失败: {e}")
        return None
    return _render_png_bytes_cached(key)


def render_dxf_to_base64(dxf_path: str, dpi: int = 200) -> str | None:
    """将 DXF 文件渲染为 base64 编码的 PNG 字符串。

    可直接嵌入 OpenAI Vision API 的 image_url 中：
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}

    Args:
        dxf_path: DXF 文件路径
        dpi: 渲染分辨率，默认 200

    Returns:
        base64 编码的 PNG 字符串，失败返回 None
    """
    png_bytes = _render_png_bytes(dxf_path, dpi=dpi)
    if png_bytes is None:
        return None

    b64 = base64.b64encode(png_bytes).decode("ascii")
    print(f"[dxf_viewer] 渲染完成: {len(b64)} 字符 base64")
    return b64


def render_dxf_to_png(
    dxf_path: str, output_path: str, dpi: int = 200
) -> bool:
    """将 DXF 文件渲染为 PNG 图片并保存到文件。

    Args:
        dxf_path: DXF 文件路径
        output_path: 输出 PNG 文件路径
        dpi: 渲染分辨率，默认 200

    Returns:
        成功返回 True
    """
    try:
        output_path = _validate_output_path(output_path)
    except ValueError as e:
        print(f"[dxf_viewer] 输出路径不允许: {e}")
        return False

    png_bytes = _render_png_bytes(dxf_path, dpi=dpi)
    if png_bytes is None:
        return False

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(png_bytes)
        print(f"[dxf_viewer] 渲染完成: {output_path}")
        return True
    except Exception as e:
        print(f"[dxf_viewer] 渲染失败: {e}")
        return False
