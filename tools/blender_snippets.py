"""共享的 Blender Python 代码片段。

Background 和 MCP 两条执行路径都需要场景初始化与场景摘要。集中在这里
可以避免两个 adapter 漂移，减少后续维护成本。
"""


def scene_setup_code() -> str:
    """返回清空场景、灯光和材质初始化代码。"""
    return r'''
# === Scene setup ===
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

world = bpy.context.scene.world
world.use_nodes = True
bg_node = world.node_tree.nodes['Background']
bg_node.inputs[0].default_value = (0.95, 0.95, 0.95, 1.0)
bg_node.inputs[1].default_value = 1.5

bpy.ops.object.light_add(type='SUN', location=(15, -10, 25))
sun = bpy.context.active_object
sun.data.energy = 1.5
sun.data.angle = 0.1

bpy.ops.object.light_add(type='AREA', location=(-5, 10, 8))
fill = bpy.context.active_object
fill.data.energy = 60.0
fill.data.size = 10.0

bpy.ops.object.light_add(type='AREA', location=(0, 0, 6))
top = bpy.context.active_object
top.data.energy = 50.0
top.data.size = 10.0

bpy.context.scene.render.engine = 'BLENDER_EEVEE'
try:
    bpy.context.scene.eevee.use_shadows = True
    bpy.context.scene.eevee.shadow_cube_size = '1024'
except AttributeError:
    pass

def _make_mat(name, color, roughness=0.8):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.roughness = roughness
    return mat

_mat_wall = _make_mat('Wall', (0.82, 0.80, 0.78, 1.0), 0.9)
_mat_column = _make_mat('Column', (0.65, 0.63, 0.60, 1.0), 0.7)
_mat_window = _make_mat('Window', (0.30, 0.55, 0.75, 1.0), 0.3)
_mat_door = _make_mat('Door', (0.55, 0.35, 0.18, 1.0), 0.6)
_mat_glass = _make_mat('Glass', (0.65, 0.82, 0.95, 0.4), 0.1)
_mat_floor = _make_mat('Floor', (0.60, 0.58, 0.55, 1.0), 0.95)
_mat_ceiling = _make_mat('Ceiling', (0.92, 0.90, 0.88, 1.0), 0.9)
'''


def scene_summary_code(prefix: str = "SCENE_SUMMARY") -> str:
    """返回输出场景对象摘要的代码。"""
    return f'''
def _component_count(obj):
    mesh = obj.data
    if len(mesh.vertices) == 0:
        return 0
    adj = {{i: set() for i in range(len(mesh.vertices))}}
    for edge in mesh.edges:
        a, b = edge.vertices
        adj[a].add(b)
        adj[b].add(a)
    seen = set()
    count = 0
    for vertex in adj:
        if vertex in seen:
            continue
        count += 1
        stack = [vertex]
        seen.add(vertex)
        while stack:
            current = stack.pop()
            for nxt in adj[current]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return count

scene_summary = {{"objects": []}}
for obj in bpy.data.objects:
    entry = {{
        "name": obj.name,
        "type": obj.type,
        "location": [round(obj.location.x, 6), round(obj.location.y, 6), round(obj.location.z, 6)],
        "dimensions": [round(obj.dimensions.x, 6), round(obj.dimensions.y, 6), round(obj.dimensions.z, 6)],
    }}
    if obj.type == 'MESH':
        entry["component_count"] = _component_count(obj)
    scene_summary["objects"].append(entry)

print("{prefix}:" + json.dumps(scene_summary, ensure_ascii=False))
'''
