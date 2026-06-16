"""BackgroundBlenderTool — subprocess 方式无头执行 Blender"""

import os
import json
import subprocess
import tempfile
from typing import List
from .blender_tool import BlenderTool, BlenderCommand, BlenderResult

# Import Config from agent package
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from agent.config import Config


# Command handler code for the bpy script
COMMAND_HANDLERS_CODE = '''\
        if operation == "extrude_wall":
            start = params["start"]
            end = params["end"]
            height = params.get("height", 2.8)
            thickness = params.get("thickness", 0.24)

            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = (dx**2 + dy**2) ** 0.5
            angle = __import__('math').atan2(dy, dx)

            bpy.ops.mesh.primitive_cube_add(
                size=1, location=(start[0] + dx/2, start[1] + dy/2, height/2)
            )
            obj = bpy.context.active_object
            obj.name = params.get("wall_id", "wall")
            obj.scale = (length/2, thickness/2, height/2)
            obj.rotation_euler.z = angle
            name = obj.name

        elif operation == "boolean_cut":
            target_id = params["target_wall_id"]
            dims = params.get("dimensions", [1, 0.3, 2.1])
            loc = params.get("location", [0, 0, 0])

            bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
            cutter = bpy.context.active_object
            cutter.name = "cutter_temp"
            cutter.scale = (dims[0]/2, dims[1]/2, dims[2]/2)

            target = bpy.data.objects.get(target_id)
            if target is None:
                for obj in bpy.data.objects:
                    if target_id in obj.name:
                        target = obj
                        break

            if target:
                mod = target.modifiers.new(name="bool_cut", type='BOOLEAN')
                mod.operation = 'DIFFERENCE'
                mod.object = cutter
                bpy.context.view_layer.objects.active = target
                bpy.ops.object.modifier_apply({"modifier": mod.name})
                bpy.data.objects.remove(cutter)
                name = target.name
            else:
                name = f"cut_failed_{target_id}"

        elif operation == "create_column":
            loc = params.get("location", [0, 0])
            radius = params.get("radius", None)
            width = params.get("width", None)
            depth = params.get("depth", None)
            height = params.get("height", 2.8)
            col_id = params.get("column_id", "column")

            if radius:
                bpy.ops.mesh.primitive_cylinder_add(
                    radius=radius, depth=height,
                    location=(loc[0], loc[1], height/2)
                )
            elif width and depth:
                bpy.ops.mesh.primitive_cube_add(
                    size=1, location=(loc[0], loc[1], height/2)
                )
                obj = bpy.context.active_object
                obj.scale = (width/2, depth/2, height/2)
            else:
                bpy.ops.mesh.primitive_cylinder_add(
                    radius=0.15, depth=height,
                    location=(loc[0], loc[1], height/2)
                )
            obj = bpy.context.active_object
            obj.name = col_id
            name = obj.name

        elif operation == "place_door":
            loc = params.get("location", [0, 0, 0])
            width = params.get("width", 0.9)
            height = params.get("height", 2.1)
            door_id = params.get("door_id", "door")

            bpy.ops.mesh.primitive_cube_add(
                size=1, location=(loc[0], loc[1], height/2)
            )
            obj = bpy.context.active_object
            obj.name = door_id
            obj.scale = (width/2, 0.05, height/2)
            obj.rotation_euler.z = params.get("rotation_z", 0)
            name = obj.name

        elif operation == "place_window":
            loc = params.get("location", [0, 0, 0])
            width = params.get("width", 1.5)
            height = params.get("height", 1.5)
            sill = params.get("sill_height", 0.9)
            win_id = params.get("window_id", "window")

            bpy.ops.mesh.primitive_cube_add(
                size=1, location=(loc[0], loc[1], sill + height/2)
            )
            obj = bpy.context.active_object
            obj.name = win_id
            obj.scale = (width/2, 0.1, height/2)
            name = obj.name

        else:
            name = f"skipped_{operation}"\
'''


BPY_SCRIPT_TEMPLATE = """\
import bpy
import json
import os

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

commands = {commands_json}

results = []
for cmd in commands:
    step_id = cmd["step_id"]
    operation = cmd["operation"]
    params = cmd["params"]

    try:
{command_handlers}

        results.append({{"step_id": step_id, "success": True, "message": name}})
    except Exception as e:
        results.append({{"step_id": step_id, "success": False,
                         "message": str(e)}})

# Save .blend
blend_path = r"{output_blend}"
os.makedirs(os.path.dirname(blend_path), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=blend_path)

# Render from multiple angles
render_angles = [(5, -5, 3), (0, -5, 3), (0, 5, 3), (5, 0, 3)]
for i, (x, y, z) in enumerate(render_angles):
    camera = bpy.data.cameras.new(f"render_cam_{{i}}")
    cam_obj = bpy.data.objects.new(f"render_cam_{{i}}", camera)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = (x, y, z)
    cam_obj.rotation_euler = (1.1, 0, 0.8)

    bpy.context.scene.camera = cam_obj
    render_path = r"{output_dir}/render_{{i:02d}}.png"
    bpy.context.scene.render.filepath = render_path
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.scene.render.resolution_x = 1920
    bpy.context.scene.render.resolution_y = 1080
    bpy.ops.render.render(write_still=True)

# Output results JSON
print("BLENDER_RESULTS:" + json.dumps(results, ensure_ascii=False))
"""

# Inject command handlers into template
BPY_SCRIPT_TEMPLATE = BPY_SCRIPT_TEMPLATE.replace(
    "{command_handlers}", COMMAND_HANDLERS_CODE
)


class BackgroundBlenderTool(BlenderTool):
    """Background mode: subprocess call to blender --background --python"""

    def __init__(self, output_dir: str | None = None):
        self._output_dir = output_dir or Config.OUTPUT_DIR
        self._connected = False

    def connect(self) -> bool:
        try:
            result = subprocess.run(
                [Config.BLENDER_EXECUTABLE, "--version"],
                capture_output=True, text=True, timeout=10
            )
            self._connected = result.returncode == 0
            if self._connected:
                ver = result.stdout.split("\n")[0].strip()
                print(f"[BackgroundBlenderTool] Blender ready: {ver}")
            return self._connected
        except FileNotFoundError:
            print("[BackgroundBlenderTool] Blender not installed or not in PATH")
            return False
        except Exception as e:
            print(f"[BackgroundBlenderTool] Connection failed: {e}")
            return False

    def disconnect(self) -> None:
        self._connected = False

    def execute(self, command: BlenderCommand) -> BlenderResult:
        results = self.execute_batch([command])
        return results[0] if results else BlenderResult(
            success=False, step_id=command.step_id, message="Batch execution failed"
        )

    def execute_batch(
        self, commands: List[BlenderCommand]
    ) -> List[BlenderResult]:
        if not commands:
            return []

        cmds_json = json.dumps([
            {
                "step_id": c.step_id,
                "operation": c.operation,
                "params": c.params,
            }
            for c in commands
        ], ensure_ascii=False)

        script_content = BPY_SCRIPT_TEMPLATE.format(
            commands_json=cmds_json,
            output_blend=os.path.join(self._output_dir, "model.blend"),
            output_dir=self._output_dir,
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(script_content)
            script_path = f.name

        try:
            os.makedirs(self._output_dir, exist_ok=True)
            result = subprocess.run(
                [Config.BLENDER_EXECUTABLE, "--background", "--python", script_path],
                capture_output=True, text=True, timeout=300,
            )

            results: List[BlenderResult] = []
            for line in result.stdout.split("\n"):
                if line.startswith("BLENDER_RESULTS:"):
                    try:
                        parsed = json.loads(line.split(":", 1)[1])
                        for r in parsed:
                            results.append(BlenderResult(
                                success=r.get("success", False),
                                step_id=r.get("step_id", 0),
                                message=r.get("message", ""),
                            ))
                    except json.JSONDecodeError:
                        pass

            if not results:
                print(f"[BackgroundBlenderTool] stderr: {result.stderr[:500]}")
                return [
                    BlenderResult(
                        success=False, step_id=c.step_id,
                        message="Blender produced no output"
                    )
                    for c in commands
                ]

            return results

        except subprocess.TimeoutExpired:
            print("[BackgroundBlenderTool] Blender execution timed out")
            return [
                BlenderResult(success=False, step_id=c.step_id, message="Timeout")
                for c in commands
            ]
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def render_viewport(
        self, output_path: str, camera_pos: tuple = (5, -5, 3)
    ) -> str | None:
        for i in range(4):
            path = os.path.join(self._output_dir, f"render_{i:02d}.png")
            if os.path.exists(path):
                return path
        return None
