#!/usr/bin/env python3
"""Test MCP Blender adapter end-to-end."""
import os, sys, json
os.chdir('/home/ao/project/cad-to-3d-agent')
sys.path.insert(0, '.')
from tools.mcp_adapter import MCPBlenderTool
from tools.blender_tool import BlenderCommand

OUT = os.path.abspath('output')
os.makedirs(OUT, exist_ok=True)

tool = MCPBlenderTool()
if not tool.connect():
    print('FAIL: Cannot connect to Blender MCP')
    sys.exit(1)

# 4 walls forming a room
commands = [
    BlenderCommand('extrude_wall', {
        'start': [0, 0], 'end': [4, 0], 'height': 2.8, 'thickness': 0.24,
        'wall_id': 'wall_north'}, step_id=1),
    BlenderCommand('extrude_wall', {
        'start': [4, 0], 'end': [4, 3], 'height': 2.8, 'thickness': 0.24,
        'wall_id': 'wall_east'}, step_id=2),
    BlenderCommand('extrude_wall', {
        'start': [4, 3], 'end': [0, 3], 'height': 2.8, 'thickness': 0.24,
        'wall_id': 'wall_south'}, step_id=3),
    BlenderCommand('extrude_wall', {
        'start': [0, 3], 'end': [0, 0], 'height': 2.8, 'thickness': 0.24,
        'wall_id': 'wall_west'}, step_id=4),
    BlenderCommand('corner_snap', {'tolerance': 0.5}, step_id=5),
    BlenderCommand('cleanup_cutters', {}, step_id=6),
    BlenderCommand('auto_camera', {}, step_id=7),
    BlenderCommand('save_blend', {'filepath': os.path.join(OUT, 'mcp_room.blend')}, step_id=8),
]

print(f'Executing {len(commands)} commands...')
for cmd in commands:
    r = tool.execute(cmd)
    status = '✅' if r.success else '❌'
    print(f'  {status} {cmd.operation}: {r.message}')

# Render with EEVEE for speed
out_dir = OUT.replace('\\', '/')
render_code = f'''
import bpy, os
from mathutils import Vector
_od = r"{out_dir}"
os.makedirs(_od, exist_ok=True)
_cx = getattr(bpy.types.Scene, '_cam_cx', 0)
_cy = getattr(bpy.types.Scene, '_cam_cy', 0)
_cz = getattr(bpy.types.Scene, '_cam_cz', 1.4)
_sp = getattr(bpy.types.Scene, '_cam_span', 5.0)
_cd = max(_sp, 5.0)
_angles = [
    (_cx+_cd, _cy-_cd, _cz+_cd*0.8),
    (_cx, _cy-_cd, _cz+_cd*0.8),
    (_cx, _cy+_cd, _cz+_cd*0.8),
    (_cx+_cd, _cy, _cz+_cd*0.8),
]
for _i, (_x, _y, _z) in enumerate(_angles):
    _cam = bpy.data.cameras.new("rc" + str(_i))
    _co = bpy.data.objects.new("rc" + str(_i), _cam)
    bpy.context.scene.collection.objects.link(_co)
    _co.location = (_x, _y, _z)
    _dir = Vector((_cx-_x, _cy-_y, _cz-_z))
    _co.rotation_euler = _dir.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = _co
    bpy.context.scene.render.filepath = os.path.join(_od, f"render_{{_i:02d}}.png")
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
    bpy.context.scene.render.resolution_x = 640
    bpy.context.scene.render.resolution_y = 480
    bpy.ops.render.render(write_still=True)
print("STEP_RESULT:rendered")
'''

print('Rendering...')
resp = tool._send_and_recv({'type': 'execute_code', 'params': {'code': render_code}}, timeout=120)
print(f'  Render: {resp.get("status", "?")}')

tool.disconnect()

print(f'\nOutput files:')
for f in sorted(os.listdir(OUT)):
    size = os.path.getsize(os.path.join(OUT, f))
    print(f'  {f}: {size/1024:.0f} KB')
