"""CAD-to-3D Agent — CLI 入口

Usage:
    python main.py <path_to_dxf>
    python main.py <path_to_dxf> --mode mcp
    python main.py <path_to_dxf> --instruction "层高改为3米"
"""

import sys
import argparse
from agent.graph import build_graph
from agent.state import AgentState
from agent.config import Config


def make_initial_state(dxf_path: str, instruction: str, mode: str) -> AgentState:
    return {
        "cad_path": dxf_path,
        "user_instruction": instruction,
        "raw_geometry": [],
        "cad_features": [],
        "modeling_plan": [],
        "user_confirmed": False,
        "user_feedback": "",
        "execution_mode": mode,
        "current_step": 0,
        "execution_results": [],
        "blender_output_path": "",
        "render_images": [],
        "validation_result": {},
        "revision_count": 0,
        "max_revisions": Config.MAX_REVISIONS,
        "validation_passed": False,
    }


def run_with_interrupts(app, initial_state: AgentState):
    """运行 Agent，处理 interrupt 暂停"""

    config = {"configurable": {"thread_id": "main"}}

    for event in app.stream(initial_state, config, stream_mode="updates"):
        node_name = list(event.keys())[0]
        node_output = event[node_name]
        print(f"\n--- 节点 [{node_name}] 执行完成 ---")

    # 最后获取最终状态
    final_state = app.get_state(config)
    return final_state.values


def main():
    errors = Config.validate()
    if errors:
        print("❌ 配置错误:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="CAD 图纸 → 3D 模型 AI Agent"
    )
    parser.add_argument("dxf_path", help="DXF 文件路径")
    parser.add_argument("--mode", choices=["mcp", "background"],
                        default="background", help="执行模式")
    parser.add_argument("--instruction", default="",
                        help="额外建模指令")
    args = parser.parse_args()

    print(f"📐 载入图纸: {args.dxf_path}")
    print(f"🔧 执行模式: {args.mode}")

    initial_state = make_initial_state(
        args.dxf_path, args.instruction, args.mode
    )

    app = build_graph()

    print("\n--- Agent 开始工作 ---\n")
    result = run_with_interrupts(app, initial_state)

    # 输出结果
    if result.get("validation_passed"):
        print(f"\n✅ 建模完成: {result.get('blender_output_path', 'output/')}")
    else:
        print(f"\n⚠️  达到最佳结果（验证未完全通过）")
        print(f"输出路径: {result.get('blender_output_path', 'output/')}")
        vr = result.get("validation_result", {})
        if vr:
            print(f"差异报告: {vr}")

    print("\n--- Agent 工作结束 ---")


if __name__ == "__main__":
    main()
