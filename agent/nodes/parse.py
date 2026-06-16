"""节点 1: DXF 解析与语义识别"""

import json
from ..state import AgentState
from ..llm import chat
from ..prompts import PARSE_SYSTEM_PROMPT
from tools.cad_parser import extract_geometry, serialize_for_llm, cluster_by_spatial


def parse_cad_node(state: AgentState) -> AgentState:
    """
    DXF 解析节点：
    1. ezdxf 读取 → 原始几何
    2. 空间聚类 → 取最大聚类
    3. 序列化文本 → LLM 语义识别 → cad_features
    """
    cad_path = state["cad_path"]

    # Step 1: 提取原始几何
    raw = extract_geometry(cad_path)
    state["raw_geometry"] = raw
    print(f"[parse] 提取到 {len(raw)} 个几何实体")

    if not raw:
        state["cad_features"] = []
        return state

    # Step 2: 空间聚类，取最大聚类（假设是主平面图）
    clusters = cluster_by_spatial(raw)
    main_cluster = max(clusters, key=len)
    print(f"[parse] 空间聚类: {len(clusters)} 个区域，主区域 {len(main_cluster)} 个实体")

    # Step 3: 序列化 → LLM 语义识别
    geometry_text = serialize_for_llm(main_cluster)
    print(f"[parse] 序列化文本长度: {len(geometry_text)} 字符")

    try:
        response = chat(
            system_prompt=PARSE_SYSTEM_PROMPT,
            user_message=geometry_text,
            max_tokens=4096,
        )
        response = response.strip()
        # 提取 JSON（去掉可能的 markdown 代码块标记）
        if response.startswith("```"):
            response = response.strip("```").strip()
            if response.startswith("json"):
                response = response[4:].strip()

        features = json.loads(response)
        if isinstance(features, dict):
            features = [features]
        state["cad_features"] = features
        print(f"[parse] LLM 识别出 {len(features)} 个建筑实体")

    except json.JSONDecodeError as e:
        print(f"[parse] LLM 返回格式错误: {e}")
        print(f"[parse] 原始响应: {response[:500]}")
        # 降级：使用原始几何数据作为特征（不带语义标签）
        state["cad_features"] = [
            {
                "type": "unknown",
                "geometry": {"vertices": e.get("vertices", [])},
                "properties": e.get("properties", {}),
            }
            for e in main_cluster[:50]
        ]

    return state
