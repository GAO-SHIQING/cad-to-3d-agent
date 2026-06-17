# CAD-to-3D Agent 操作步骤

---

## 一、环境准备

### 1.1 确保 Python 3.11+ 可用

```bash
python --version
# 应输出: Python 3.11.x 或更高
```

### 1.2 确保 Blender 已安装

```bash
blender --version 2>/dev/null || which blender || echo "Blender is not installed"
```

如果未安装：

Ubuntu/Debian:
```bash
sudo apt install blender
```

macOS:
```bash
brew install blender
```

Windows:
从 https://www.blender.org/download/ 下载安装包，安装后确保 `blender` 在 PATH 中

### 1.3 验证 Blender 可执行

```bash
blender --background --python-expr "import bpy; print('OK')" 2>/dev/null | grep OK
# 应输出: OK
```

---

## 二、安装项目

### 2.1 进入项目目录

```bash
cd ~/project/cad-to-3d-agent
```

### 2.2 创建虚拟环境（可选但推荐）

```bash
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
# 或 .venv\Scripts\activate  (Windows)
```

### 2.3 安装 Python 依赖

```bash
pip install -r requirements.txt
```

应安装 7 个包：langgraph、langgraph-checkpoint、openai、ezdxf、python-dotenv、matplotlib、pytest

### 2.4 验证安装

```bash
python -c "
from agent.graph import build_graph
from tools.cad_parser import extract_geometry
print('All imports OK')
"
```

---

## 三、配置 API Key

### 3.1 创建 .env

```bash
cp .env.example .env
```

### 3.2 编辑 .env

```bash
nano .env    # 或用任何编辑器
```

填入你的配置：

```bash
# 必填
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 按需修改（使用代理或兼容接口时）
OPENAI_BASE_URL=https://api.openai.com/v1

# 模型名称（默认 gpt-5.5）
LLM_MODEL=gpt-5.5

# Blender 路径（默认 'blender'，PATH 中能找到的话不用改）
BLENDER_EXECUTABLE=blender
```

如果用的是兼容接口（如国内的代理/中转服务），修改 `OPENAI_BASE_URL` 即可，不硬编码提供商。

### 3.3 验证配置

```bash
python -c "from agent.config import Config; print(Config.LLM_MODEL); Config.validate()"
```

应输出模型名且无报错。

---

## 四、验证测试

### 4.1 运行测试

```bash
python -m pytest tests/ -v
```

应输出 73 passed

### 4.2 验证图形

```bash
python -c "from agent.graph import build_graph; g = build_graph(); print('Nodes:', [n for n in g.nodes if not n.startswith('__')])"
# Nodes: ['parse', 'plan', 'confirm', 'execute', 'validate']
```

### 4.3 验证 DXF 解析

```bash
python -c "
from tools.cad_parser import extract_geometry
entities = extract_geometry('examples/single_room.dxf')
print(f'{len(entities)} entities:')
for e in entities:
    print(f'  {e[\"type\"]} on layer \"{e[\"layer\"]}\"')
"
```

应输出 53 个实体（52 LINE + 1 INSERT）

### 4.4 验证 LLM 连接

```bash
python -c "
from agent.llm import chat
response = chat('Reply with just: OK', 'hello', max_tokens=10)
print('LLM response:', response.strip())
"
```

如果这里报错或超时，说明 API key / 网络配置有问题，回到步骤三排查。

---

## 五、运行 Agent

### 5.1 基础运行

```bash
python main.py examples/single_room.dxf
```

### 5.2 运行流程

你会看到 3 个步骤的进度：

```
1. [parse_node]  提取几何 → LLM 识别实体
2. [plan_node]   LLM 生成建模计划
3. [confirm_node] 暂停，等待你的决定
```

在 `[confirm_node]` 时，你可以：
- `y` — 批准，继续执行建模
- `n` — 重做规划
- `把层高改成3米` — 用自然语言修改

### 5.3 完整输出

```
4. [execute_node]  调用 Blender 生成 .blend 和渲染图
5. [validate_node]  运行几何检查和LLM语义验证
```

结果文件：
- `output/model.blend` — 三维模型
- `output/render_00.png ~ render_03.png` — 多角度渲染图

---

## 六、查看结果

### 6.1 用 Blender 打开模型

```bash
blender output/model.blend
```

### 6.2 直接查看渲染图

```bash
ls -la output/render_*.png
```

---

## 七、其他运行方式

### 7.1 Background 模式（subprocess 无头执行，无需启动 Blender GUI）

```bash
python main.py examples/single_room.dxf --mode background
```

适合不需要逐步调试、一条命令直接出结果的场景。默认模式为 `mcp`（通过 TCP 连接 Blender MCP Add-on）。

### 7.2 自动批准建模计划

```bash
python main.py examples/single_room.dxf --auto-confirm
```

跳过人工确认步骤，LLM 规划后自动执行。

### 7.3 带额外指令

```bash
python main.py examples/single_room.dxf --instruction "层高改为3米，墙体厚度改为200mm"
```

### 7.4 用自己的 DXF 文件

```bash
python main.py /path/to/your/building.dxf
```

---

## 八、故障排查

| 现象 | 检查 |
|------|------|
| `ModuleNotFoundError` | `pip install -r requirements.txt` 重新执行 |
| LLM 调用超时/报错 | `.env` 中 API key 是否正确、网络是否通 |
| Blender 执行失败 | `blender --version` 是否正常、Blender 版本是否 ≥3.6 |
| DXF 文件解析为空 | DXF 是否包含 ENTITIES section、用 ezdxf 命令行工具检查：`ezdxf audit your_file.dxf` |
| 73 测试有失败 | `git status` 检查是不是有文件被意外修改 |
