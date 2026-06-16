"""AgentState — LangGraph 中央状态定义"""

from typing import TypedDict, List, Dict, Any


class AgentState(TypedDict):
    # === 输入 ===
    cad_path: str                       # DXF 文件路径
    user_instruction: str               # 用户额外指令（可选）

    # === 解析结果 ===
    raw_geometry: List[Dict]            # ezdxf 提取的原始几何数据
    cad_features: List[Dict[str, Any]]  # LLM 语义识别后的结构化实体

    # === 规划结果 ===
    modeling_plan: List[Dict[str, Any]] # 建模操作序列
    user_confirmed: bool                # 用户是否已确认
    user_feedback: str                  # 用户在确认节点的反馈

    # === 执行状态 ===
    execution_mode: str                 # "mcp" | "background"
    current_step: int                   # 当前执行步骤
    execution_results: List[Dict]       # 各步骤执行结果
    blender_output_path: str            # .blend 文件路径
    render_images: List[str]            # 渲染图路径列表

    # === 验证状态 ===
    validation_result: Dict             # 验证结果
    revision_count: int                 # 修订次数
    max_revisions: int                  # 最大修订次数 (默认3)
    validation_passed: bool             # 验证是否通过
