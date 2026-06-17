"""BackgroundBlenderTool — subprocess 方式无头执行 Blender"""

import os
import json
import subprocess
import tempfile
from typing import List
from .blender_tool import BlenderTool, BlenderCommand, BlenderResult
from .blender_snippets import scene_setup_code, scene_summary_code

# Import Config from agent package
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from agent.config import Config


def _cube_scale_for_dimensions(width: float, depth: float, height: float) -> tuple[float, float, float]:
    """Blender primitive_cube_add(size=1) 时 scale 等于最终尺寸。"""
    dims = (float(width), float(depth), float(height))
    if any(d <= 0 for d in dims):
        raise ValueError("cube dimensions must be positive")
    return dims


# === Blender Python script template (run inside blender --background --python) ===

BPY_SCRIPT_TEMPLATE = r'''
import bpy
import json
import os
import math
from mathutils import Vector

{scene_setup_code}

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
                obj.scale = (length, thickness, height)
                obj.rotation_euler.z = angle
                obj.data.materials.append(_mat_wall)
                name = obj.name

        elif operation == "boolean_cut":
            target_id = params.get("target_wall_id", "")
            dims = params.get("dimensions", [1, 0.3, 2.1])
            loc = params.get("location", [0, 0, 0])
            rotation = params.get("rotation_z", 0.0)
            wall_thickness = params.get("wall_thickness", 0.24)

            target = bpy.data.objects.get(target_id)
            if target is None:
                for obj in bpy.data.objects:
                    if target_id in obj.name:
                        target = obj
                        break

            # Force cutter depth to fully penetrate wall (min 0.5m wall-normal)
            cut_depth = max(dims[1], wall_thickness * 2.0, 0.5)
            bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
            cutter = bpy.context.active_object
            cutter.name = "cutter_temp"
            cutter.scale = (dims[0], cut_depth, dims[2])
            cutter.rotation_euler.z = rotation

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
                obj.scale = (width, depth, height)
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
            wall_angle = params.get("rotation_z", 0)

            # Door panel: position at opening center, offset along wall normal for hinge
            door_thick = 0.06
            hinge_offset = params.get("wall_thickness", 0.24) * 0.5
            hinge_x = loc[0] + hinge_offset * math.cos(wall_angle + math.pi/2)
            hinge_y = loc[1] + hinge_offset * math.sin(wall_angle + math.pi/2)

            bpy.ops.mesh.primitive_cube_add(
                size=1, location=(hinge_x, hinge_y, height / 2),
            )
            obj = bpy.context.active_object
            obj.name = door_id
            obj.scale = (width, door_thick, height)
            obj.rotation_euler.z = wall_angle
            obj.data.materials.append(_mat_door)
            name = obj.name

        elif operation == "place_window":
            loc = params.get("location", [0, 0, 0])
            width = params.get("width", 1.5)
            height = params.get("height", 1.5)
            sill = params.get("sill_height", 0.9)
            win_id = params.get("window_id", "window")
            wall_thick = params.get("wall_thickness", 0.24)

            # Window frame: slightly larger than opening, flush with wall surface
            frame_depth = wall_thick * 1.2
            bpy.ops.mesh.primitive_cube_add(
                size=1, location=(loc[0], loc[1], sill + height / 2),
            )
            obj = bpy.context.active_object
            obj.name = win_id
            obj.scale = (width, frame_depth, height)
            obj.rotation_euler.z = params.get("rotation_z", 0)
            obj.data.materials.append(_mat_window)
            name = obj.name

        # === Post-processing operations ===

        elif operation == "join_and_merge":
            merge_threshold = params.get("merge_threshold", 0.3)
            wall_objs = [o for o in bpy.data.objects if o.type == 'MESH'
                         and (o.name.startswith('wall_') or o.name.startswith('column_'))]

            if len(wall_objs) >= 2:
                for wall in wall_objs:
                    bpy.ops.object.select_all(action='DESELECT')
                    wall.select_set(True)
                    bpy.context.view_layer.objects.active = wall
                    bpy.ops.object.mode_set(mode='EDIT')
                    bpy.ops.mesh.select_all(action='SELECT')
                    bpy.ops.mesh.remove_doubles(threshold=merge_threshold)
                    bpy.ops.mesh.normals_make_consistent(inside=False)
                    bpy.ops.object.mode_set(mode='OBJECT')

                name = f"cleaned_{len(wall_objs)}_independent_walls_at_{merge_threshold}m"
            elif len(wall_objs) == 1:
                name = "single_wall_no_join_needed"
            else:
                name = "no_walls_to_join"

        elif operation == "create_floor_ceiling":
            floor_info = params.get("floor_bounds")
            wall_h = params.get("wall_height", 2.8)

            if floor_info:
                center = floor_info.get("center", [0, 0])
                size = floor_info.get("size", [5, 5])
                cx, cy = center[0], center[1]
                sx, sy = size[0], size[1]
            else:
                # Fallback: compute from all mesh objects
                meshes = [o for o in bpy.data.objects if o.type == 'MESH']
                if meshes:
                    mnx = mny = mnz = float('inf')
                    mxx = mxy = mxz = float('-inf')
                    for obj in meshes:
                        for corner in obj.bound_box:
                            wc = obj.matrix_world @ Vector(corner)
                            mnx = min(mnx, wc.x); mny = min(mny, wc.y); mnz = min(mnz, wc.z)
                            mxx = max(mxx, wc.x); mxy = max(mxy, wc.y); mxz = max(mxz, wc.z)
                    margin = 0.3
                    cx = (mnx + mxx) / 2
                    cy = (mny + mxy) / 2
                    sx = (mxx - mnx) + 2 * margin
                    sy = (mxy - mny) + 2 * margin
                else:
                    cx = cy = 0
                    sx = sy = 5

            # Floor: plane at z = -0.03 (just below wall bottom)
            floor_z = -0.03
            bpy.ops.mesh.primitive_plane_add(
                size=1, location=(cx, cy, floor_z)
            )
            floor = bpy.context.active_object
            floor.name = "floor"
            floor.scale = (sx, sy, 1)
            floor.data.materials.append(_mat_floor)

            # Ceiling: plane at z = wall_height + 0.03
            ceil_z = wall_h + 0.03
            bpy.ops.mesh.primitive_plane_add(
                size=1, location=(cx, cy, ceil_z)
            )
            ceiling = bpy.context.active_object
            ceiling.name = "ceiling"
            ceiling.scale = (sx, sy, 1)
            ceiling.data.materials.append(_mat_ceiling)

            name = "floor_and_ceiling_created"

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

{scene_summary_code}

# Output results JSON
print("BLENDER_RESULTS:" + json.dumps(results, ensure_ascii=False))
'''


def build_script_content(commands_json: str, output_blend: str, output_dir: str) -> str:
    """构造 Background Blender 执行脚本。"""
    return BPY_SCRIPT_TEMPLATE.replace(
        "{commands_json}", commands_json
    ).replace(
        "{output_blend}", output_blend
    ).replace(
        "{output_dir}", output_dir
    ).replace(
        "{scene_setup_code}", scene_setup_code()
    ).replace(
        "{scene_summary_code}", scene_summary_code(prefix="BLENDER_SCENE_SUMMARY")
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

        script_content = build_script_content(
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
            scene_summary = None
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
                elif line.startswith("BLENDER_SCENE_SUMMARY:"):
                    try:
                        scene_summary = json.loads(line.split(":", 1)[1])
                    except json.JSONDecodeError:
                        scene_summary = None

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

            if scene_summary is not None:
                for r in results:
                    r.output = {"scene_summary": scene_summary}

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
