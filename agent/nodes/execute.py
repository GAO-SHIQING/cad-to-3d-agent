"""节点 4: 建模执行"""

import os
from ..state import AgentState
from tools.blender_tool import BlenderCommand, BlenderTool
from tools.background_adapter import BackgroundBlenderTool
from tools.mcp_adapter import MCPBlenderTool
from ..config import Config
from tools.wall_topology import infer_floor_bounds


def _create_tool(mode: str) -> BlenderTool:
    """根据执行模式创建对应的 BlenderTool 实例"""
    if mode == "mcp":
        return MCPBlenderTool(host=Config.MCP_HOST, port=Config.MCP_PORT)
    return BackgroundBlenderTool(output_dir=Config.OUTPUT_DIR)


def _plan_to_commands(plan: list[dict]) -> list[BlenderCommand]:
    """将 modeling_plan 转为 BlenderCommand 列表"""
    commands = []
    for step in plan:
        commands.append(BlenderCommand(
            operation=step.get("operation", "unknown"),
            params=step.get("params", {}),
            step_id=step.get("step_id", 0),
        ))
    return commands


def _normalize_coordinates(commands: list[BlenderCommand]) -> tuple[float, float]:
    """将 DXF 坐标归一化到原点附近，返回偏移量 (offset_x, offset_y)"""
    all_x, all_y = [], []
    for cmd in commands:
        p = cmd.params
        for key in ("start", "end", "location", "loc", "position"):
            if key in p and isinstance(p[key], (list, tuple)) and len(p[key]) >= 2:
                all_x.append(p[key][0])
                all_y.append(p[key][1])

    if not all_x:
        return (0.0, 0.0)

    offset_x = min(all_x)
    offset_y = min(all_y)

    for cmd in commands:
        p = cmd.params
        for key in ("start", "end", "location", "loc", "position"):
            if key in p and isinstance(p[key], (list, tuple)) and len(p[key]) >= 2:
                p[key][0] -= offset_x
                p[key][1] -= offset_y

    print(f"[execute] 坐标归一化: offset=({offset_x:.1f}, {offset_y:.1f})")
    return (offset_x, offset_y)


def _create_post_processing_commands(
    base_step_id: int,
    output_dir: str,
    floor_bounds: dict | None = None,
    wall_height: float = 2.8,
) -> list[BlenderCommand]:
    """创建后处理命令：墙体合并焊接、地面天花板、清理、相机、保存、渲染"""
    # 使用绝对路径：MCP 模式下 Blender 进程工作目录不可控
    output_blend = os.path.abspath(os.path.join(output_dir, "model.blend"))
    output_dir_abs = os.path.abspath(output_dir)

    commands = [
        # 1. 将所有墙体 Join 成一个 Mesh → Merge by Distance → 水密闭合
        BlenderCommand(
            operation="join_and_merge",
            params={"merge_threshold": 0.3},
            step_id=base_step_id + 1,
        ),
        # 2. 生成地面和天花板
        BlenderCommand(
            operation="create_floor_ceiling",
            params={
                "floor_bounds": floor_bounds,
                "wall_height": wall_height,
            },
            step_id=base_step_id + 2,
        ),
        # 3. 清理残余 cutter 对象
        BlenderCommand(
            operation="cleanup_cutters",
            params={},
            step_id=base_step_id + 3,
        ),
        # 4. 自动相机
        BlenderCommand(
            operation="auto_camera",
            params={},
            step_id=base_step_id + 4,
        ),
        # 5. 保存 .blend (绝对路径)
        BlenderCommand(
            operation="save_blend",
            params={"filepath": output_blend},
            step_id=base_step_id + 5,
        ),
        # 6. 多角度渲染 (绝对路径)
        BlenderCommand(
            operation="render",
            params={
                "output_dir": output_dir_abs,
                "resolution_x": 1920,
                "resolution_y": 1080,
            },
            step_id=base_step_id + 6,
        ),
    ]
    return commands


def _try_execute(
    all_commands: list[BlenderCommand],
    mode: str,
) -> tuple[list[dict] | None, BlenderTool | None]:
    """尝试用指定模式执行命令。返回 (results, tool) 或 (None, None) 表示失败。"""
    tool = _create_tool(mode)

    if not tool.connect():
        print(f"[execute] [{mode.upper()}] 无法连接")
        return None, None

    try:
        results = tool.execute_batch(all_commands)
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count
        print(f"[execute] [{mode.upper()}] 执行完成: {success_count} 成功, {fail_count} 失败")

        cmd_ops = {c.step_id: c.operation for c in all_commands}
        formatted = [
            {
                "step_id": r.step_id,
                "operation": cmd_ops.get(r.step_id, "unknown"),
                "success": r.success,
                "message": r.message,
                "output": r.output,
                "render_path": r.render_path,
            }
            for r in results
        ]
        return formatted, tool
    except Exception as e:
        print(f"[execute] [{mode.upper()}] 执行异常: {e}")
        return None, None


def execute_node(state: AgentState) -> AgentState:
    """
    执行节点 (MCP 优先，Background 保底):

    执行策略：
      1. 主路径: MCPBlenderTool（TCP 直连 Blender MCP Add-on）
         - 优势：逐步执行，可观测每步结果，适合开发调试
         - 要求：Blender 需提前启动并加载 MCP Add-on
      2. 保底路径: BackgroundBlenderTool（subprocess 调用 blender --background）
         - 当 MCP 连接失败且 FALLBACK_TO_BACKGROUND=true 时自动启用
         - 优势：零依赖，Blender 未启动也能运行
    """
    plan = state.get("modeling_plan", [])
    requested_mode = state.get("execution_mode", "mcp")

    if not plan:
        print("[execute] 没有建模计划，跳过执行")
        state["execution_results"] = []
        return state

    commands = _plan_to_commands(plan)

    # === 坐标归一化（DXF mm 坐标 → Blender 米制原点） ===
    _normalize_coordinates(commands)

    # === 追加后处理命令 ===
    max_step_id = max(c.step_id for c in commands) if commands else 0
    cad_features = state.get("cad_features", [])
    floor_info = infer_floor_bounds(cad_features)
    wall_height = floor_info.get("wall_height", 2.8) if floor_info else 2.8
    post_commands = _create_post_processing_commands(
        max_step_id, Config.OUTPUT_DIR, floor_info, wall_height
    )
    all_commands = commands + list(post_commands)

    print(f"[execute] 共 {len(all_commands)} 步 "
          f"({len(commands)} 建模 + {len(post_commands)} 后处理)")

    # === 执行策略: MCP 优先 → Background 保底 ===

    # 确定尝试顺序
    modes_to_try = []
    if requested_mode == "mcp":
        modes_to_try.append("mcp")
        if Config.FALLBACK_TO_BACKGROUND:
            modes_to_try.append("background")
    else:
        modes_to_try.append("background")

    results = None
    used_tool = None
    used_mode = None

    for mode in modes_to_try:
        label = "[PRIMARY]" if mode == modes_to_try[0] else "[FALLBACK]"
        print(f"\n[execute] {label} 尝试 {mode.upper()} 模式 ...")
        results, used_tool = _try_execute(all_commands, mode)
        if results is not None:
            used_mode = mode
            break
        if used_tool:
            used_tool.disconnect()
            used_tool = None

    if results is None:
        print("[execute] [FATAL] 所有执行模式均失败，无法建模")
        state["execution_results"] = []
        return state

    if used_mode != requested_mode:
        print(f"[execute] ⚠ 已从 {requested_mode} 回退到 {used_mode} 模式执行")

    try:
        state["execution_results"] = results

        # 不同模式下 render_viewport 行为不同：
        #   MCP 模式: 返回 None（渲染由 Background 管线的 render 命令完成）
        #   Background 模式: 检查 output_dir 下的 render_*.png
        render_path = used_tool.render_viewport(
            os.path.abspath(os.path.join(Config.OUTPUT_DIR, "render.png"))
        )
        if render_path:
            state["render_images"] = [render_path]

        state["blender_output_path"] = os.path.abspath(
            os.path.join(Config.OUTPUT_DIR, "model.blend")
        )

    finally:
        used_tool.disconnect()

    return state
