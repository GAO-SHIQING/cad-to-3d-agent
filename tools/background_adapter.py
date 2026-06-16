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


# === Blender Python script template (run inside blender --background --python) ===

BPY_SCRIPT_TEMPLATE = r'''
import bpy
import json
import os
import math
from mathutils import Vector

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

commands = {commands_json}

# ============================================================
# Execute all commands (modeling + post-processing)
# ============================================================
results = []

# Persistent scene-level camera state (shared between auto_camera and render)
_cam_center = (0, 0, 1.4)
_cam_span = 5.0

for cmd in commands:
    step_id = cmd["step_id"]
    operation = cmd["operation"]
    params = cmd["params"]
    name = f"unknown_{step_id}"

    try:
        # === Modeling operations ===

        if operation == "extrude_wall":
            start = params["start"]
            end = params["end"]
            height = params.get("height", 2.8)
            thickness = params.get("thickness", 0.24)

            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = (dx**2 + dy**2) ** 0.5
            angle = math.atan2(dy, dx)

            if length < 0.001:
                name = f"skipped_zero_length_wall_{step_id}"
            else:
                bpy.ops.mesh.primitive_cube_add(
                    size=1,
                    location=(start[0] + dx / 2, start[1] + dy / 2, height / 2),
                )
                obj = bpy.context.active_object
                obj.name = params.get("wall_id", f"wall_{step_id:02d}")
                obj.scale = (length / 2, thickness / 2, height / 2)
                obj.rotation_euler.z = angle
                name = obj.name

        elif operation == "boolean_cut":
            target_id = params.get("target_wall_id", "")
            dims = params.get("dimensions", [1, 0.3, 2.1])
            loc = params.get("location", [0, 0, 0])

            target = bpy.data.objects.get(target_id)
            if target is None:
                for obj in bpy.data.objects:
                    if target_id in obj.name:
                        target = obj
                        break

            bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
            cutter = bpy.context.active_object
            cutter.name = "cutter_temp"
            cutter.scale = (dims[0] / 2, dims[1] / 2, dims[2] / 2)

            if target:
                mod = target.modifiers.new(name="bool_cut", type='BOOLEAN')
                mod.operation = 'DIFFERENCE'
                mod.object = cutter
                bpy.context.view_layer.objects.active = target
                try:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    name = target.name
                except Exception as e:
                    try:
                        bpy.ops.object.modifier_apply({"modifier": mod.name})
                        name = target.name
                    except Exception:
                        raise RuntimeError(f"modifier_apply failed: {e}")
            else:
                name = f"cut_failed_no_target_{target_id}"

            # cleanup cutter
            bpy.ops.object.select_all(action='DESELECT')
            cutter.select_set(True)
            bpy.context.view_layer.objects.active = cutter
            try:
                bpy.ops.object.delete(use_global=False)
            except Exception:
                pass

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
                    location=(loc[0], loc[1], height / 2),
                )
            elif width and depth:
                bpy.ops.mesh.primitive_cube_add(
                    size=1, location=(loc[0], loc[1], height / 2),
                )
                obj = bpy.context.active_object
                obj.scale = (width / 2, depth / 2, height / 2)
            else:
                bpy.ops.mesh.primitive_cylinder_add(
                    radius=0.15, depth=height,
                    location=(loc[0], loc[1], height / 2),
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
                size=1, location=(loc[0], loc[1], height / 2),
            )
            obj = bpy.context.active_object
            obj.name = door_id
            obj.scale = (width / 2, 0.05, height / 2)
            obj.rotation_euler.z = params.get("rotation_z", 0)
            name = obj.name

        elif operation == "place_window":
            loc = params.get("location", [0, 0, 0])
            width = params.get("width", 1.5)
            height = params.get("height", 1.5)
            sill = params.get("sill_height", 0.9)
            win_id = params.get("window_id", "window")

            bpy.ops.mesh.primitive_cube_add(
                size=1, location=(loc[0], loc[1], sill + height / 2),
            )
            obj = bpy.context.active_object
            obj.name = win_id
            obj.scale = (width / 2, 0.1, height / 2)
            name = obj.name

        # === Post-processing operations ===

        elif operation == "corner_snap":
            tol = params.get("tolerance", 0.3)
            wall_objs = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('wall_')]

            if len(wall_objs) >= 2:
                wall_data = []
                for w in wall_objs:
                    sl = Vector((-0.5, 0.0, 0.0))
                    el = Vector((0.5, 0.0, 0.0))
                    ws = w.matrix_world @ sl
                    we = w.matrix_world @ el
                    wall_data.append((w, ws, we))

                for i in range(len(wall_data)):
                    for j in range(i + 1, len(wall_data)):
                        w1, s1, e1 = wall_data[i]
                        w2, s2, e2 = wall_data[j]
                        for p1, p2, wa, isa, wb, isb in [
                            (s1, s2, w1, True, w2, True),
                            (s1, e2, w1, True, w2, False),
                            (e1, s2, w1, False, w2, True),
                            (e1, e2, w1, False, w2, False),
                        ]:
                            d = (p1 - p2).length
                            if 0.001 < d <= tol:
                                snap = (p1 + p2) * 0.5
                                sc, ec = (s1, e1) if wa == w1 else (s2, e2)
                                nc = (snap + ec) * 0.5 if isa else (sc + snap) * 0.5
                                nl = (ec - snap).length if isa else (snap - sc).length
                                wa.location.x = nc.x; wa.location.y = nc.y
                                wa.scale.x = nl
                                sc, ec = (s2, e2) if wb == w2 else (s1, e1)
                                nc = (snap + ec) * 0.5 if isb else (sc + snap) * 0.5
                                nl = (ec - snap).length if isb else (snap - sc).length
                                wb.location.x = nc.x; wb.location.y = nc.y
                                wb.scale.x = nl
                                break
            name = "corner_snap_done"

        elif operation == "cleanup_cutters":
            cutters = [o for o in bpy.data.objects if o.name.startswith('cutter_temp')]
            if cutters:
                bpy.ops.object.select_all(action='DESELECT')
                for c in cutters:
                    c.select_set(True)
                bpy.context.view_layer.objects.active = cutters[0]
                bpy.ops.object.delete(use_global=False)
            name = f"cleaned_{len(cutters)}_cutters"

        elif operation == "auto_camera":
            meshes = [o for o in bpy.data.objects if o.type == 'MESH']
            if meshes:
                mnx = mny = mnz = float('inf')
                mxx = mxy = mxz = float('-inf')
                for obj in meshes:
                    for corner in obj.bound_box:
                        wc = obj.matrix_world @ Vector(corner)
                        mnx = min(mnx, wc.x); mny = min(mny, wc.y); mnz = min(mnz, wc.z)
                        mxx = max(mxx, wc.x); mxy = max(mxy, wc.y); mxz = max(mxz, wc.z)
                _cam_center = ((mnx+mxx)/2, (mny+mxy)/2, (mnz+mxz)/2)
                _cam_span = max(mxx-mnx, mxy-mny) * 1.8
                name = f"camera_framed"
            else:
                _cam_center = (0, 0, 1.4)
                _cam_span = 5.0
                name = "camera_default"

        elif operation == "save_blend":
            fp = params.get("filepath", "./output/model.blend")
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=fp)
            name = "saved"

        elif operation == "render":
            output_dir = params.get("output_dir", "./output")
            rx = params.get("resolution_x", 1920)
            ry = params.get("resolution_y", 1080)
            os.makedirs(output_dir, exist_ok=True)
            cd = max(_cam_span, 5.0)
            cx, cy, cz = _cam_center
            angles = [
                (cx+cd, cy-cd, cz+cd*0.8),
                (cx, cy-cd, cz+cd*0.8),
                (cx, cy+cd, cz+cd*0.8),
                (cx+cd, cy, cz+cd*0.8),
            ]
            for idx, (x, y, z) in enumerate(angles):
                cam = bpy.data.cameras.new(f"render_cam_{idx}")
                co = bpy.data.objects.new(f"render_cam_{idx}", cam)
                bpy.context.scene.collection.objects.link(co)
                co.location = (x, y, z)
                direction = Vector((cx-x, cy-y, cz-z))
                co.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
                bpy.context.scene.camera = co
                bpy.context.scene.render.filepath = os.path.join(output_dir, f"render_{idx:02d}.png")
                bpy.context.scene.render.engine = 'CYCLES'
                bpy.context.scene.render.resolution_x = rx
                bpy.context.scene.render.resolution_y = ry
                bpy.ops.render.render(write_still=True)
            name = "rendered"

        else:
            name = f"skipped_{operation}"

        results.append({
            "step_id": step_id,
            "operation": operation,
            "success": True,
            "message": name,
        })

    except Exception as e:
        results.append({
            "step_id": step_id,
            "operation": operation,
            "success": False,
            "message": str(e),
        })

# Output results JSON
print("BLENDER_RESULTS:" + json.dumps(results, ensure_ascii=False))
'''


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

        script_content = BPY_SCRIPT_TEMPLATE.replace(
            "{commands_json}", cmds_json
        ).replace(
            "{output_blend}", os.path.join(self._output_dir, "model.blend")
        ).replace(
            "{output_dir}", self._output_dir
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

            # Log debug lines
            for line in result.stdout.split("\n"):
                if any(line.startswith(prefix) for prefix in (
                    "BLENDER_NORMALIZE:", "BLENDER_SNAP:", "BLENDER_CLEANUP:",
                    "BLENDER_CAMERA:"
                )):
                    print(f"[BackgroundBlenderTool] {line}")

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
