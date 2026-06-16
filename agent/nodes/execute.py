"""节点 4: 建模执行"""

import os
import time
import socket
import subprocess
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


def _check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """检测 TCP 端口是否可达"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _launch_blender_mcp() -> subprocess.Popen | None:
    """启动 Blender GUI 进程（自动加载 MCP Add-on 监听 9876 端口）

    Blender 启动后会自动执行 addon.py 的 register()，
    其中创建 BlenderMCPServer 并调用 start() 监听 TCP 9876。

    返回 subprocess.Popen 对象，调用方负责管理生命周期。
    """
    blender_bin = Config.BLENDER_EXECUTABLE

    if not blender_bin or not os.path.isfile(blender_bin):
        print("[execute] Blender 可执行文件不存在，跳过自动启动")
        return None

    print(f"[execute] 正在启动 Blender (MCP Add-on 将自动监听 "
          f"{Config.MCP_HOST}:{Config.MCP_PORT}) ...")

    try:
        # 使用 Popen 启动 Blender GUI（非 background 模式，
        # 因为 MCP add-on 依赖 bpy.app.timers 主线程事件循环）
        proc = subprocess.Popen(
            [blender_bin],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # 脱离终端，Blender 关闭不影响 Agent
        )
        return proc
    except FileNotFoundError:
        print(f"[execute] 找不到 Blender: {blender_bin}")
        return None
    except Exception as e:
        print(f"[execute] 启动 Blender 失败: {e}")
        return None


def _wait_for_mcp(
    host: str,
    port: int,
    timeout: float = 30.0,
    interval: float = 1.0,
) -> bool:
    """轮询等待 MCP 端口就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _check_port(host, port, timeout=1.0):
            return True
        time.sleep(interval)
    return False


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

    # === 执行策略: MCP 优先 → 自动启动 → Background 保底 ===
    #
    #  尝试顺序:
    #    1. MCP 直连 (Blender 已运行)
    #    2. 启动 Blender → 等待 MCP 端口就绪 → MCP 直连
    #    3. Background subprocess 保底

    results = None
    used_tool = None
    used_mode = None
    blender_proc = None

    # ── 第一阶段: 尝试 MCP ──
    if requested_mode == "mcp":
        print(f"\n[execute] [PRIMARY] 尝试 MCP 直连 "
              f"({Config.MCP_HOST}:{Config.MCP_PORT}) ...")
        results, used_tool = _try_execute(all_commands, "mcp")
        if results is not None:
            used_mode = "mcp"
        else:
            if used_tool:
                used_tool.disconnect()
                used_tool = None

            # ── 第二阶段: MCP 连不上 → 尝试自动启动 Blender ──
            if Config.MCP_AUTO_LAUNCH:
                print("\n[execute] [RETRY] MCP 直连失败，尝试启动 Blender ...")
                blender_proc = _launch_blender_mcp()

                if blender_proc:
                    print(f"[execute] Blender 进程已启动 (PID={blender_proc.pid})，"
                          f"等待 MCP 端口就绪 ...")
                    ready = _wait_for_mcp(
                        Config.MCP_HOST,
                        Config.MCP_PORT,
                        timeout=Config.MCP_LAUNCH_TIMEOUT,
                    )

                    if ready:
                        print(f"[execute] MCP 端口已就绪，重新尝试连接 ...")
                        results, used_tool = _try_execute(all_commands, "mcp")
                        if results is not None:
                            used_mode = "mcp"
                        elif used_tool:
                            used_tool.disconnect()
                            used_tool = None
                    else:
                        print(f"[execute] 等待超时 ({Config.MCP_LAUNCH_TIMEOUT}s)，"
                              f"MCP 端口仍未就绪")

    # ── 第三阶段: MCP 不可用 → Background 保底 ──
    if results is None and Config.FALLBACK_TO_BACKGROUND:
        print("\n[execute] [FALLBACK] MCP 路径不可用，回退到 Background 模式 ...")
        results, used_tool = _try_execute(all_commands, "background")
        if results is not None:
            used_mode = "background"
        elif used_tool:
            used_tool.disconnect()
            used_tool = None

    # ── 所有尝试均失败 ──
    if results is None:
        print("[execute] [FATAL] 所有执行模式均失败 (MCP + 启动 + Background)，无法建模")
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
