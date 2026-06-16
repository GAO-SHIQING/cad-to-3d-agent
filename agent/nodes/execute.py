"""节点 4: 建模执行"""

import os
from ..state import AgentState
from tools.blender_tool import BlenderCommand, BlenderTool
from tools.background_adapter import BackgroundBlenderTool
from tools.mcp_adapter import MCPBlenderTool
from ..config import Config


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
    base_step_id: int, output_dir: str
) -> list[BlenderCommand]:
    """创建后处理命令：角点吸附、清理、相机、保存、渲染"""
    output_blend = os.path.join(output_dir, "model.blend")

    return [
        BlenderCommand(
            operation="corner_snap",
            params={"tolerance": 0.3},
            step_id=base_step_id + 1,
        ),
        BlenderCommand(
            operation="cleanup_cutters",
            params={},
            step_id=base_step_id + 2,
        ),
        BlenderCommand(
            operation="auto_camera",
            params={},
            step_id=base_step_id + 3,
        ),
        BlenderCommand(
            operation="save_blend",
            params={"filepath": output_blend},
            step_id=base_step_id + 4,
        ),
        BlenderCommand(
            operation="render",
            params={
                "output_dir": output_dir,
                "resolution_x": 1920,
                "resolution_y": 1080,
            },
            step_id=base_step_id + 5,
        ),
    ]


def execute_node(state: AgentState) -> AgentState:
    """
    执行节点：
    1. modeling_plan → 坐标归一化 → BlenderCommand 列表
    2. 追加后处理命令（角点吸附、清理、相机、保存、渲染）
    3. 根据 execution_mode 选择适配器
    4. 批量执行命令
    5. 记录结果到 state
    """
    plan = state.get("modeling_plan", [])
    mode = state.get("execution_mode", "mcp")

    if not plan:
        print("[execute] 没有建模计划，跳过执行")
        state["execution_results"] = []
        return state

    commands = _plan_to_commands(plan)

    # === 坐标归一化（DXF mm 坐标 → Blender 米制原点） ===
    _normalize_coordinates(commands)

    # === 追加后处理命令 ===
    max_step_id = max(c.step_id for c in commands) if commands else 0
    post_commands = _create_post_processing_commands(max_step_id, Config.OUTPUT_DIR)
    all_commands = commands + list(post_commands)

    print(f"[execute] 准备执行 {len(all_commands)} 个步骤 "
          f"({len(commands)} 建模 + {len(post_commands)} 后处理) (模式: {mode})")

    tool = _create_tool(mode)

    if not tool.connect():
        print("[execute] [FAIL]  无法连接到 Blender")
        state["execution_results"] = []
        return state

    try:
        results = tool.execute_batch(all_commands)

        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count
        print(f"[execute] 执行完成: {success_count} 成功, {fail_count} 失败")

        # Build execution results with operation names for geometry checker
        cmd_ops = {c.step_id: c.operation for c in all_commands}
        state["execution_results"] = [
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

        render_path = tool.render_viewport(f"{Config.OUTPUT_DIR}/render.png")
        if render_path:
            state["render_images"] = [render_path]

        state["blender_output_path"] = f"{Config.OUTPUT_DIR}/model.blend"

    finally:
        tool.disconnect()

    return state
