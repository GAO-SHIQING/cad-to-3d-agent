"""节点 1: DXF 解析与语义识别 — 视觉通道 (CAD MCP)"""

import json
from ..state import AgentState
from ..llm import chat_with_vision
from ..prompts import PARSE_SYSTEM_PROMPT
from tools.cad_parser import extract_geometry, cluster_by_spatial, infer_features_from_geometry
from tools.dxf_viewer import render_dxf_to_base64
from tools.wall_topology import cluster_wall_endpoints


def parse_cad_node(state: AgentState) -> AgentState:
    """
    DXF 解析节点（纯视觉通道）：
    1. ezdxf 提取原始几何 → raw_geometry（供下游几何检查使用）
    2. DXF 渲染为 PNG 位图
    3. Vision LLM 看图识别建筑实体 → cad_features
    """
    cad_path = state["cad_path"]

    # Step 1: 提取原始几何（供 geometry_checker 和其他下游节点使用）
    raw = extract_geometry(cad_path)
    state["raw_geometry"] = raw
    print(f"[parse] 提取到 {len(raw)} 个几何实体")

    if not raw:
        state["cad_features"] = []
        return state

    # Step 2: 空间聚类，取最大聚类（聚焦主平面图）
    clusters = cluster_by_spatial(raw)
    main_cluster = max(clusters, key=len)
    print(f"[parse] 空间聚类: {len(clusters)} 个区域，主区域 {len(main_cluster)} 个实体")

    # Step 3: 渲染 DXF 为 PNG 位图
    image_b64 = render_dxf_to_base64(cad_path)
    if not image_b64:
        print("[parse] CAD 渲染失败，无法继续")
        state["cad_features"] = [
            {
                "type": "unknown",
                "geometry": {"vertices": ent.get("vertices", [])},
                "properties": ent.get("properties", {}),
            }
            for ent in main_cluster[:50]
        ]
        return state

    # Step 4: Vision LLM 看图识别实体
    print(f"[parse] CAD 渲染图已生成，发送至 Vision LLM 进行语义识别")
    user_message = (
        "请仔细观察这张建筑平面图的渲染图，识别图中的建筑实体。\n\n"
        "注意：\n"
        "- 图中包含坐标刻度，可用于估算实体位置和尺寸\n"
        "- 坐标单位为毫米\n"
        "- 墙体表现为双平行线\n"
        "- 门表现为墙体间的矩形开口（约700-1200mm宽），可能附带弧形开门轨迹\n"
        "- 窗表现为墙体间的矩形开口（约600-3600mm宽）\n"
        "- 柱表现为独立的矩形或圆形截面\n\n"
        "请按照系统指令的 JSON 格式输出所有识别的实体。"
    )
    try:
        response = chat_with_vision(
            system_prompt=PARSE_SYSTEM_PROMPT,
            user_message=user_message,
            image_base64=image_b64,
            max_tokens=4096,
        )

        response = response.strip()
        if response.startswith("```"):
            response = response.strip("```").strip()
            if response.startswith("json"):
                response = response[4:].strip()

        features = json.loads(response)
        if isinstance(features, dict):
            features = [features]
        print(f"[parse] Vision LLM 识别出 {len(features)} 个建筑实体")
        should_snap_wall_endpoints = True

    except Exception as e:
        print(f"[parse] Vision LLM 失败，启用确定性兜底: {e}")
        features = infer_features_from_geometry(raw)
        should_snap_wall_endpoints = False
        print(f"[parse] 几何兜底识别出 {len(features)} 个建筑实体")

    if features and should_snap_wall_endpoints:
        # === 墙体拓扑推断：端点聚类归并 ===
        # Vision LLM 提取的坐标天然有误差，需将相近端点归并为共享角点
        features = cluster_wall_endpoints(features)
    state["cad_features"] = features

    return state
