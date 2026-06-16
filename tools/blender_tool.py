"""BlenderTool — Blender 操作的抽象接口"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class BlenderCommand:
    """单个 Blender 操作命令"""
    operation: str              # 操作名
    params: Dict[str, Any]      # 参数
    step_id: int                # 对应 modeling_plan 的步骤


@dataclass
class BlenderResult:
    """Blender 操作执行结果"""
    success: bool
    step_id: int
    message: str = ""           # 成功消息或错误描述
    output: Any = None          # 创建的对象引用或额外数据
    render_path: str | None = None  # 执行后截图路径


class BlenderTool(ABC):
    """Blender 操作的抽象接口

    两个实现:
    - MCPBlenderTool: 通过 TCP Socket 与 Blender Add-on 通信
    - BackgroundBlenderTool: subprocess 调用 blender --background
    """

    @abstractmethod
    def connect(self) -> bool:
        """建立与 Blender 的连接"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        ...

    @abstractmethod
    def execute(self, command: BlenderCommand) -> BlenderResult:
        """执行单个建模命令"""
        ...

    @abstractmethod
    def execute_batch(
        self, commands: List[BlenderCommand]
    ) -> List[BlenderResult]:
        """批量执行建模命令"""
        ...

    @abstractmethod
    def render_viewport(
        self, output_path: str, camera_pos: tuple = (5, -5, 3)
    ) -> str | None:
        """渲染当前视口截图，返回文件路径"""
        ...
