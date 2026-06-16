"""节点 4: 建模执行"""

from ..state import AgentState
from tools.blender_tool import BlenderCommand, BlenderTool
from tools.background_adapter import BackgroundBlenderTool
from tools.mcp_adapter import MCPBlenderTool
from ..config import Config


def _create_tool(mode: str) -> BlenderTool:
    """根据执行模式创建对应的 BlenderTool 实例"""
    if mode == "mcp":
        return MCPBlenderTool()
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


def execute_node(state: AgentState) -> AgentState:
    """
    执行节点：
    1. 将 modeling_plan 转为 BlenderCommand 列表
    2. 根据 execution_mode 选择适配器
    3. 批量执行命令
    4. 记录结果到 state
    """
    plan = state.get("modeling_plan", [])
    mode = state.get("execution_mode", "background")

    if not plan:
        print("[execute] 没有建模计划，跳过执行")
        state["execution_results"] = []
        return state

    commands = _plan_to_commands(plan)
    print(f"[execute] 准备执行 {len(commands)} 个步骤 (模式: {mode})")

    tool = _create_tool(mode)

    if not tool.connect():
        print("[execute] ❌ 无法连接到 Blender")
        state["execution_results"] = []
        return state

    try:
        results = tool.execute_batch(commands)

        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count
        print(f"[execute] 执行完成: {success_count} 成功, {fail_count} 失败")

        state["execution_results"] = [
            {
                "step_id": r.step_id,
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
