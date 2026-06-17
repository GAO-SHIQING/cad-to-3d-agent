"""MCPBlenderTool — TCP Socket communication with Blender MCP Add-on

Protocol: line-delimited JSON over TCP port 9876
  Request:  {"type": "execute_code", "params": {"code": "<bpy python>"}}
  Response: {"status": "success", "result": {"executed": true, "result": "<stdout>"}}

Security: All LLM-generated parameters pass through validate_params() before use.
Numeric fields are type-checked; string IDs are regex-validated; complex data
(vectors, lists) is embedded via json.dumps()/json.loads() to prevent injection.
"""

import json
import re
import socket
from typing import List, Any, Dict
from .blender_tool import BlenderTool, BlenderCommand, BlenderResult

# ── Validation ──────────────────────────────────────────────────────────────

# Safe ID pattern: alphanumeric + underscore + hyphen, max 64 chars
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')


def _check_num(v: Any, default: float = 0.0) -> float:
    """Validate v is int or float, return as float; else return default."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return default


def _check_num_list(v: Any, length: int, default: list) -> list:
    """Validate v is a list of exactly `length` numbers; else return default."""
    if not isinstance(v, list) or len(v) != length:
        return list(default)
    result = []
    for x in v:
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            result.append(float(x))
        else:
            return list(default)
    return result


def _check_str_id(v: Any, default: str) -> str:
    """Validate v is a safe identifier string; else return default."""
    if isinstance(v, str) and _SAFE_ID_RE.match(v):
        return v
    return default


def _check_path(v: Any, default: str) -> str:
    """Validate v is a filesystem-safe path string (no shell metacharacters)."""
    if not isinstance(v, str):
        return default
    # Reject paths containing shell-injection characters
    if any(c in v for c in (';', '|', '&', '$', '`', '(', ')', '<', '>')):
        return default
    return v


def _cube_scale_for_dimensions(width: float, depth: float, height: float) -> tuple[float, float, float]:
    dims = (float(width), float(depth), float(height))
    if any(d <= 0 for d in dims):
        raise ValueError("cube dimensions must be positive")
    return dims


def validate_params(operation: str, params: dict) -> dict:
    """Validate and sanitize LLM-generated params for a given operation.
    Returns a clean dict; unknown keys are dropped, bad values replaced with
    safe defaults. This is the security boundary between untrusted LLM output
    and code generation.
    """
    clean: dict = {}

    if operation == "extrude_wall":
        clean["start"] = _check_num_list(params.get("start"), 2, [0, 0])
        clean["end"] = _check_num_list(params.get("end"), 2, [0, 0])
        clean["height"] = _check_num(params.get("height"), 2.8)
        clean["thickness"] = _check_num(params.get("thickness"), 0.24)
        clean["wall_id"] = _check_str_id(params.get("wall_id"), "wall_unknown")

    elif operation == "boolean_cut":
        clean["target_wall_id"] = _check_str_id(params.get("target_wall_id"), "wall_unknown")
        clean["dimensions"] = _check_num_list(params.get("dimensions"), 3, [1.0, 0.3, 2.1])
        clean["location"] = _check_num_list(params.get("location"), 3, [0, 0, 0])
        clean["rotation_z"] = _check_num(params.get("rotation_z"), 0.0)
        clean["wall_thickness"] = _check_num(params.get("wall_thickness"), 0.24)

    elif operation == "create_column":
        clean["location"] = _check_num_list(params.get("location"), 2, [0, 0])
        clean["height"] = _check_num(params.get("height"), 2.8)
        clean["column_id"] = _check_str_id(params.get("column_id"), "column_unknown")
        radius = params.get("radius")
        width = params.get("width")
        depth = params.get("depth")
        if radius is not None:
            clean["radius"] = _check_num(radius, 0.15)
        elif width is not None and depth is not None:
            clean["width"] = _check_num(width, 0.3)
            clean["depth"] = _check_num(depth, 0.3)

    elif operation == "place_door":
        clean["location"] = _check_num_list(params.get("location"), 3, [0, 0, 0])
        clean["width"] = _check_num(params.get("width"), 0.9)
        clean["height"] = _check_num(params.get("height"), 2.1)
        clean["door_id"] = _check_str_id(params.get("door_id"), "door_unknown")
        clean["rotation_z"] = _check_num(params.get("rotation_z"), 0.0)

    elif operation == "place_window":
        clean["location"] = _check_num_list(params.get("location"), 3, [0, 0, 0])
        clean["width"] = _check_num(params.get("width"), 1.5)
        clean["height"] = _check_num(params.get("height"), 1.5)
        clean["sill_height"] = _check_num(params.get("sill_height"), 0.9)
        clean["window_id"] = _check_str_id(params.get("window_id"), "window_unknown")

    elif operation == "join_and_merge":
        clean["merge_threshold"] = _check_num(params.get("merge_threshold"), 0.3)

    elif operation == "create_floor_ceiling":
        clean["floor_bounds"] = params.get("floor_bounds")  # dict, trust the pipeline
        clean["wall_height"] = _check_num(params.get("wall_height"), 2.8)

    elif operation in ("cleanup_cutters", "auto_camera"):
        pass  # No params needed

    elif operation == "save_blend":
        clean["filepath"] = _check_path(params.get("filepath", "./output/model.blend"),
                                        "./output/model.blend")

    elif operation == "render":
        clean["output_dir"] = _check_path(params.get("output_dir", "./output"),
                                          "./output")
        clean["resolution_x"] = int(_check_num(params.get("resolution_x"), 1920))
        clean["resolution_y"] = int(_check_num(params.get("resolution_y"), 1080))

    return clean


# ── Code generation (uses validated params + json.dumps for safe embedding) ──

def _generate_bpy_for_command(operation: str, params: dict, step_id: int) -> str:
    """Generate a self-contained bpy Python snippet for one command.

    All data values are embedded via json.dumps() → json.loads() to prevent
    code injection. String identifiers go through _check_str_id (validated).
    """
    p = validate_params(operation, params)

    if operation == "extrude_wall":
        start_j = json.dumps(p["start"])
        end_j = json.dumps(p["end"])
        height_j = json.dumps(p["height"])
        thickness_j = json.dumps(p["thickness"])
        wall_id_j = json.dumps(p["wall_id"])
        return (
            "import bpy, math, json\n"
            f"_s=json.loads({start_j!r}); _e=json.loads({end_j!r}); "
            f"_h=json.loads({height_j!r}); _thk=json.loads({thickness_j!r}); "
            f"_wid=json.loads({wall_id_j!r})\n"
            "_dx=_e[0]-_s[0]; _dy=_e[1]-_s[1]\n"
            "_len=(_dx**2+_dy**2)**0.5\n"
            "if _len<0.001:\n"
            f"    print('STEP_RESULT:skipped_zero_wall_{step_id}')\n"
            "else:\n"
            "    _ang=math.atan2(_dy,_dx)\n"
            "    bpy.ops.mesh.primitive_cube_add(size=1,"
            "location=(_s[0]+_dx/2,_s[1]+_dy/2,_h/2))\n"
            "    _o=bpy.context.active_object; _o.name=_wid\n"
            "    _o.scale=(_len,_thk,_h); _o.rotation_euler.z=_ang\n"
            "    _mat=bpy.data.materials.get('Wall')\n"
            "    if _mat: _o.data.materials.append(_mat)\n"
            '    print("STEP_RESULT:"+_o.name)\n')

    elif operation == "boolean_cut":
        tid_j = json.dumps(p["target_wall_id"])
        dims_j = json.dumps(p["dimensions"])
        loc_j = json.dumps(p["location"])
        return (
            "import bpy, json\n"
            f"_tid=json.loads({tid_j!r}); _dims=json.loads({dims_j!r}); "
            f"_loc=json.loads({loc_j!r}); _rot=json.loads({json.dumps(p.get('rotation_z', 0.0))!r}); "
            f"_wall_thickness=json.loads({json.dumps(p.get('wall_thickness', 0.24))!r})\n"
            "bpy.ops.mesh.primitive_cube_add(size=1,location=_loc)\n"
            '_cutter=bpy.context.active_object; _cutter.name="cutter_temp"\n'
            "_cutter.scale=(_dims[0],max(_dims[1], _wall_thickness * 2.0, 0.5),_dims[2])\n"
            "_cutter.rotation_euler.z=_rot\n"
            "_target=bpy.data.objects.get(_tid)\n"
            "if _target is None:\n"
            "    for _o in bpy.data.objects:\n"
            "        if _tid in _o.name: _target=_o; break\n"
            "if _target:\n"
            "    _mod=_target.modifiers.new(name='bool_cut',type='BOOLEAN')\n"
            "    _mod.operation='DIFFERENCE'; _mod.object=_cutter\n"
            "    bpy.context.view_layer.objects.active=_target\n"
            "    try: bpy.ops.object.modifier_apply(modifier=_mod.name)\n"
            "    except Exception:\n"
            '        try: bpy.ops.object.modifier_apply({"modifier":_mod.name})\n'
            '        except Exception as _e_: raise RuntimeError("modifier_apply:"+str(_e_))\n'
            '    print("STEP_RESULT:"+_target.name)\n'
            "else:\n"
            '    print("STEP_RESULT:cut_failed_no_target_"+_tid)\n'
            "bpy.ops.object.select_all(action='DESELECT')\n"
            "_cutter.select_set(True)\n"
            "bpy.context.view_layer.objects.active=_cutter\n"
            "try: bpy.ops.object.delete(use_global=False)\n"
            "except Exception: pass\n")

    elif operation == "create_column":
        loc_j = json.dumps(p["location"])
        height_j = json.dumps(p["height"])
        col_id_j = json.dumps(p["column_id"])
        radius = p.get("radius")
        width = p.get("width")
        depth = p.get("depth")

        if radius is not None:
            r_j = json.dumps(radius)
            geom = (f"bpy.ops.mesh.primitive_cylinder_add(radius=json.loads({r_j!r}),"
                    f"depth=json.loads({height_j!r}),"
                    f"location=(_loc[0],_loc[1],json.loads({height_j!r})/2))")
        elif width is not None and depth is not None:
            w_j = json.dumps(width)
            d_j = json.dumps(depth)
            geom = (f"bpy.ops.mesh.primitive_cube_add(size=1,"
                    f"location=(_loc[0],_loc[1],json.loads({height_j!r})/2));"
                    f"_o=bpy.context.active_object;"
                    f"_o.scale=(json.loads({w_j!r}),json.loads({d_j!r}),"
                    f"json.loads({height_j!r}))")
        else:
            geom = (f"bpy.ops.mesh.primitive_cylinder_add(radius=0.15,"
                    f"depth=json.loads({height_j!r}),"
                    f"location=(_loc[0],_loc[1],json.loads({height_j!r})/2))")

        return (
            "import bpy, json\n"
            f"_loc=json.loads({loc_j!r}); _cid=json.loads({col_id_j!r})\n"
            f"{geom}\n"
            "_o=bpy.context.active_object; _o.name=_cid\n"
            'print("STEP_RESULT:"+_o.name)\n')

    elif operation == "place_door":
        loc_j = json.dumps(p["location"])
        width_j = json.dumps(p["width"])
        height_j = json.dumps(p["height"])
        door_id_j = json.dumps(p["door_id"])
        rot_j = json.dumps(p["rotation_z"])
        return (
            "import bpy, json\n"
            f"_loc=json.loads({loc_j!r}); _w=json.loads({width_j!r}); "
            f"_h=json.loads({height_j!r}); _did=json.loads({door_id_j!r}); "
            f"_rot=json.loads({rot_j!r})\n"
            "bpy.ops.mesh.primitive_cube_add(size=1,location=(_loc[0],_loc[1],_h/2))\n"
            "_o=bpy.context.active_object; _o.name=_did\n"
            "_o.scale=(_w,0.05,_h); _o.rotation_euler.z=_rot\n"
            "_mat=bpy.data.materials.get('Door')\n"
            "if _mat: _o.data.materials.append(_mat)\n"
            'print("STEP_RESULT:"+_o.name)\n')

    elif operation == "place_window":
        loc_j = json.dumps(p["location"])
        width_j = json.dumps(p["width"])
        height_j = json.dumps(p["height"])
        sill_j = json.dumps(p["sill_height"])
        win_id_j = json.dumps(p["window_id"])
        return (
            "import bpy, json\n"
            f"_loc=json.loads({loc_j!r}); _w=json.loads({width_j!r}); "
            f"_h=json.loads({height_j!r}); _sill=json.loads({sill_j!r}); "
            f"_wid=json.loads({win_id_j!r})\n"
            "bpy.ops.mesh.primitive_cube_add(size=1,"
            "location=(_loc[0],_loc[1],_sill+_h/2))\n"
            "_o=bpy.context.active_object; _o.name=_wid\n"
            "_o.scale=(_w,0.1,_h)\n"
            "_mat=bpy.data.materials.get('Window')\n"
            "if _mat: _o.data.materials.append(_mat)\n"
            'print("STEP_RESULT:"+_o.name)\n')

    elif operation == "join_and_merge":
        mt_j = json.dumps(p["merge_threshold"])
        return (
            "import bpy, json\n"
            "from mathutils import Vector\n"
            f"_mt=json.loads({mt_j!r})\n"
            "_w=[o for o in bpy.data.objects if o.type=='MESH' and "
            "(o.name.startswith('wall_') or o.name.startswith('column_'))]\n"
            "if len(_w)>=2:\n"
            "    bpy.ops.object.select_all(action='DESELECT')\n"
            "    for _o in _w: _o.select_set(True)\n"
            "    bpy.context.view_layer.objects.active=_w[0]\n"
            "    bpy.ops.object.join()\n"
            "    _j=bpy.context.active_object\n"
            "    bpy.ops.object.mode_set(mode='EDIT')\n"
            "    bpy.ops.mesh.select_all(action='SELECT')\n"
            "    bpy.ops.mesh.remove_doubles(threshold=_mt)\n"
            "    bpy.ops.mesh.normals_make_consistent(inside=False)\n"
            "    bpy.ops.object.mode_set(mode='OBJECT')\n"
            "    print('STEP_RESULT:joined_'+str(len(_w))+'_walls')\n"
            "elif len(_w)==1:\n"
            "    print('STEP_RESULT:single_wall_no_join')\n"
            "else:\n"
            "    print('STEP_RESULT:no_walls_to_join')\n")

    elif operation == "create_floor_ceiling":
        fb_j = json.dumps(p.get("floor_bounds"))
        wh_j = json.dumps(p.get("wall_height"))
        return (
            "import bpy, json\n"
            "from mathutils import Vector\n"
            f"_fb=json.loads({fb_j!r}); _wh=json.loads({wh_j!r})\n"
            "if _fb:\n"
            "    _cx=_fb['center'][0]; _cy=_fb['center'][1]\n"
            "    _sx=_fb['size'][0]; _sy=_fb['size'][1]\n"
            "else:\n"
            "    _objs=[o for o in bpy.data.objects if o.type=='MESH']\n"
            "    if _objs:\n"
            "        _mnx=_mny=float('inf'); _mxx=_mxy=float('-inf')\n"
            "        for o in _objs:\n"
            "            for c in o.bound_box:\n"
            "                _w=o.matrix_world@Vector(c)\n"
            "                _mnx=min(_mnx,_w.x); _mny=min(_mny,_w.y)\n"
            "                _mxx=max(_mxx,_w.x); _mxy=max(_mxy,_w.y)\n"
            "        _cx=(_mnx+_mxx)/2; _cy=(_mny+_mxy)/2\n"
            "        _sx=(_mxx-_mnx)+0.6; _sy=(_mxy-_mny)+0.6\n"
            "    else:\n"
            "        _cx=_cy=0; _sx=_sy=5\n"
            "# Floor\n"
            "bpy.ops.mesh.primitive_plane_add(size=1,location=(_cx,_cy,-0.03))\n"
            "_fl=bpy.context.active_object; _fl.name='floor'\n"
            "_fl.scale=(_sx,_sy,1)\n"
            "_mat_fl=bpy.data.materials.get('Floor')\n"
            "if _mat_fl: _fl.data.materials.append(_mat_fl)\n"
            "# Ceiling\n"
            "bpy.ops.mesh.primitive_plane_add(size=1,location=(_cx,_cy,_wh+0.03))\n"
            "_cl=bpy.context.active_object; _cl.name='ceiling'\n"
            "_cl.scale=(_sx,_sy,1)\n"
            "_mat_cl=bpy.data.materials.get('Ceiling')\n"
            "if _mat_cl: _cl.data.materials.append(_mat_cl)\n"
            "print('STEP_RESULT:floor_and_ceiling_created')\n")

    elif operation == "cleanup_cutters":
        return (
            "import bpy\n"
            "_ct=[o for o in bpy.data.objects if o.name.startswith('cutter_temp')]\n"
            "if _ct:\n"
            "    bpy.ops.object.select_all(action='DESELECT')\n"
            "    for _c in _ct: _c.select_set(True)\n"
            "    bpy.context.view_layer.objects.active=_ct[0]\n"
            "    bpy.ops.object.delete(use_global=False)\n"
            "print('STEP_RESULT:cleaned_'+str(len(_ct))+'_cutters')\n")

    elif operation == "auto_camera":
        return (
            "import bpy\n"
            "from mathutils import Vector\n"
            "_objs=[o for o in bpy.data.objects if o.type=='MESH']\n"
            "if _objs:\n"
            "    _mnx=_mny=_mnz=float('inf')\n"
            "    _mxx=_mxy=_mxz=float('-inf')\n"
            "    for _obj in _objs:\n"
            "        for _corner in _obj.bound_box:\n"
            "            _w=_obj.matrix_world@Vector(_corner)\n"
            "            _mnx=min(_mnx,_w.x);_mny=min(_mny,_w.y);_mnz=min(_mnz,_w.z)\n"
            "            _mxx=max(_mxx,_w.x);_mxy=max(_mxy,_w.y);_mxz=max(_mxz,_w.z)\n"
            "    bpy.types.Scene._cam_cx=(_mnx+_mxx)/2\n"
            "    bpy.types.Scene._cam_cy=(_mny+_mxy)/2\n"
            "    bpy.types.Scene._cam_cz=(_mnz+_mxz)/2\n"
            "    bpy.types.Scene._cam_span=max(_mxx-_mnx,_mxy-_mny)*1.8\n"
            "else:\n"
            "    bpy.types.Scene._cam_cx=0; bpy.types.Scene._cam_cy=0\n"
            "    bpy.types.Scene._cam_cz=1.4; bpy.types.Scene._cam_span=5.0\n"
            "print('STEP_RESULT:camera_framed')\n")

    elif operation == "save_blend":
        fp_j = json.dumps(p["filepath"])
        return (
            "import bpy, os, json\n"
            f"_fp=json.loads({fp_j!r})\n"
            "os.makedirs(os.path.dirname(_fp),exist_ok=True)\n"
            "bpy.ops.wm.save_as_mainfile(filepath=_fp)\n"
            "print('STEP_RESULT:saved')\n")

    elif operation == "render":
        od_j = json.dumps(p["output_dir"])
        rx_j = json.dumps(p["resolution_x"])
        ry_j = json.dumps(p["resolution_y"])
        return (
            "import bpy, os, json\n"
            "from mathutils import Vector\n"
            f"_od=json.loads({od_j!r}); _rx=json.loads({rx_j!r}); _ry=json.loads({ry_j!r})\n"
            "os.makedirs(_od,exist_ok=True)\n"
            "_cx=getattr(bpy.types.Scene,'_cam_cx',0)\n"
            "_cy=getattr(bpy.types.Scene,'_cam_cy',0)\n"
            "_cz=getattr(bpy.types.Scene,'_cam_cz',1.4)\n"
            "_sp=getattr(bpy.types.Scene,'_cam_span',5.0)\n"
            "_cd=max(_sp,5.0)\n"
            "_angles=[(_cx+_cd,_cy-_cd,_cz+_cd*0.8),(_cx,_cy-_cd,_cz+_cd*0.8),\n"
            "         (_cx,_cy+_cd,_cz+_cd*0.8),(_cx+_cd,_cy,_cz+_cd*0.8)]\n"
            "for _i,(_x,_y,_z) in enumerate(_angles):\n"
            '    _cam=bpy.data.cameras.new("render_cam_"+str(_i))\n'
            '    _co=bpy.data.objects.new("render_cam_"+str(_i),_cam)\n'
            "    bpy.context.scene.collection.objects.link(_co)\n"
            "    _co.location=(_x,_y,_z)\n"
            "    _dir=Vector((_cx-_x,_cy-_y,_cz-_z))\n"
            '    _co.rotation_euler=_dir.to_track_quat("-Z","Y").to_euler()\n'
            "    bpy.context.scene.camera=_co\n"
            "    bpy.context.scene.render.filepath=os.path.join(_od,\n"
            '        "render_"+str(_i).zfill(2)+".png")\n'
            "    bpy.context.scene.render.engine='CYCLES'\n"
            "    bpy.context.scene.render.resolution_x=_rx\n"
            "    bpy.context.scene.render.resolution_y=_ry\n"
            "    bpy.ops.render.render(write_still=True)\n"
            "print('STEP_RESULT:rendered')\n")

    else:
        # Unknown operation – log it but don't execute anything dangerous
        safe_op = _check_str_id(operation, "unknown")
        return f'print("STEP_RESULT:skipped_{safe_op}")\n'


# ── MCPBlenderTool ──────────────────────────────────────────────────────────

class MCPBlenderTool(BlenderTool):
    """MCP mode: TCP Socket → Blender MCP Add-on.

    Requires Blender running with the MCP add-on listening on host:port.
    Protocol: {"type":"execute_code","params":{"code":"..."}} → {"status":"success",...}

    All commands pass through validate_params() before code generation to
    prevent LLM-output code injection.
    """

    def __init__(self, host: str = "localhost", port: int = 9876):
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._connected = False

    def connect(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(10)
            self._sock.connect((self._host, self._port))
            self._connected = True
            print(f"[MCPBlenderTool] Connected to Blender at {self._host}:{self._port}")
            return True
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            print(f"[MCPBlenderTool] Connection failed: {e}")
            print("[MCPBlenderTool] Make sure Blender is running with the MCP add-on")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._connected = False

    def _send_and_recv(self, payload: dict, timeout: float = 120.0) -> dict:
        """Send JSON payload and receive JSON response.

        The MCP add-on responds with a single JSON object (no trailing newline).
        """
        if not self._sock or not self._connected:
            return {"status": "error", "message": "Not connected"}

        self._sock.settimeout(timeout)
        request = json.dumps(payload, ensure_ascii=False) + "\n"
        self._sock.sendall(request.encode())

        response_data = b""
        while True:
            chunk = self._sock.recv(65536)
            if not chunk:
                break
            response_data += chunk
            # Try to parse as complete JSON (add-on sends no trailing newline)
            try:
                json.loads(response_data.decode())
                break
            except json.JSONDecodeError:
                continue

        try:
            return json.loads(response_data.decode().strip())
        except json.JSONDecodeError:
            raw = response_data.decode().strip()[:200]
            return {"status": "error", "message": f"Invalid JSON: {raw}"}

    def execute(self, command: BlenderCommand) -> BlenderResult:
        """Execute a single command via MCP execute_code."""
        try:
            code = _generate_bpy_for_command(
                command.operation, command.params, command.step_id
            )
            resp = self._send_and_recv({
                "type": "execute_code",
                "params": {"code": code},
            })

            if resp.get("status") == "success":
                result_text = resp.get("result", {}).get("result", "")
                name = "ok"
                for line in result_text.split("\n"):
                    if line.startswith("STEP_RESULT:"):
                        name = line.split(":", 1)[1].strip()
                return BlenderResult(
                    success=True,
                    step_id=command.step_id,
                    message=name,
                    output=resp,
                )
            else:
                return BlenderResult(
                    success=False,
                    step_id=command.step_id,
                    message=resp.get("message", "Unknown error"),
                    output=resp,
                )
        except socket.timeout:
            return BlenderResult(
                success=False, step_id=command.step_id, message="timed out"
            )
        except Exception as e:
            return BlenderResult(
                success=False, step_id=command.step_id, message=str(e)
            )

    def _scene_setup_code(self) -> str:
        """生成场景初始化代码（清空 + 灯光 + 材质），与 Background 模式对齐"""
        return (
            "import bpy\n"
            "# === Clear scene ===\n"
            "bpy.ops.object.select_all(action='SELECT')\n"
            "bpy.ops.object.delete(use_global=False)\n"
            "\n"
            "# === World background ===\n"
            "world = bpy.context.scene.world\n"
            "world.use_nodes = True\n"
            "bg_node = world.node_tree.nodes['Background']\n"
            "bg_node.inputs[0].default_value = (0.95, 0.95, 0.95, 1.0)\n"
            "bg_node.inputs[1].default_value = 1.5\n"
            "\n"
            "# === Sun light ===\n"
            "bpy.ops.object.light_add(type='SUN', location=(15, -10, 25))\n"
            "sun = bpy.context.active_object\n"
            "sun.data.energy = 1.5\n"
            "sun.data.angle = 0.1\n"
            "\n"
            "# === Fill light ===\n"
            "bpy.ops.object.light_add(type='AREA', location=(-5, 10, 8))\n"
            "fill = bpy.context.active_object\n"
            "fill.data.energy = 60.0\n"
            "fill.data.size = 10.0\n"
            "\n"
            "# === Top area light ===\n"
            "bpy.ops.object.light_add(type='AREA', location=(0, 0, 6))\n"
            "top = bpy.context.active_object\n"
            "top.data.energy = 50.0\n"
            "top.data.size = 10.0\n"
            "\n"
            "# === EEVEE settings ===\n"
            "bpy.context.scene.render.engine = 'BLENDER_EEVEE'\n"
            "try:\n"
            "    bpy.context.scene.eevee.use_shadows = True\n"
            "    bpy.context.scene.eevee.shadow_cube_size = '1024'\n"
            "except AttributeError:\n"
            "    pass\n"
            "\n"
            "# === Material library ===\n"
            "def _make_mat(name, color, roughness=0.8):\n"
            "    mat = bpy.data.materials.new(name)\n"
            "    mat.diffuse_color = color\n"
            "    mat.roughness = roughness\n"
            "    return mat\n"
            "_mat_wall = _make_mat('Wall', (0.82, 0.80, 0.78, 1.0), 0.9)\n"
            "_mat_column = _make_mat('Column', (0.65, 0.63, 0.60, 1.0), 0.7)\n"
            "_mat_window = _make_mat('Window', (0.30, 0.55, 0.75, 1.0), 0.3)\n"
            "_mat_door = _make_mat('Door', (0.55, 0.35, 0.18, 1.0), 0.6)\n"
            "_mat_glass = _make_mat('Glass', (0.65, 0.82, 0.95, 0.4), 0.1)\n"
            "_mat_floor = _make_mat('Floor', (0.60, 0.58, 0.55, 1.0), 0.95)\n"
            "_mat_ceiling = _make_mat('Ceiling', (0.92, 0.90, 0.88, 1.0), 0.9)\n"
            "print('SCENE_SETUP:ok')\n"
        )

    def _scene_summary_code(self) -> str:
        """生成场景摘要代码，用于诊断对象尺寸和墙体连通性。"""
        return (
            "import bpy, json\n"
            "def _component_count(obj):\n"
            "    mesh = obj.data\n"
            "    if len(mesh.vertices) == 0:\n"
            "        return 0\n"
            "    adj = {i: set() for i in range(len(mesh.vertices))}\n"
            "    for edge in mesh.edges:\n"
            "        a, b = edge.vertices\n"
            "        adj[a].add(b); adj[b].add(a)\n"
            "    seen = set(); count = 0\n"
            "    for vertex in adj:\n"
            "        if vertex in seen:\n"
            "            continue\n"
            "        count += 1\n"
            "        stack = [vertex]; seen.add(vertex)\n"
            "        while stack:\n"
            "            current = stack.pop()\n"
            "            for nxt in adj[current]:\n"
            "                if nxt not in seen:\n"
            "                    seen.add(nxt); stack.append(nxt)\n"
            "    return count\n"
            "summary = {'objects': []}\n"
            "for obj in bpy.data.objects:\n"
            "    entry = {\n"
            "        'name': obj.name,\n"
            "        'type': obj.type,\n"
            "        'location': [round(obj.location.x, 6), round(obj.location.y, 6), round(obj.location.z, 6)],\n"
            "        'dimensions': [round(obj.dimensions.x, 6), round(obj.dimensions.y, 6), round(obj.dimensions.z, 6)],\n"
            "    }\n"
            "    if obj.type == 'MESH':\n"
            "        entry['component_count'] = _component_count(obj)\n"
            "    summary['objects'].append(entry)\n"
            "print('SCENE_SUMMARY:' + json.dumps(summary, ensure_ascii=False))\n"
        )

    def execute_batch(
        self, commands: List[BlenderCommand]
    ) -> List[BlenderResult]:
        """主执行路径: MCP 模式批量执行。

        1. 场景初始化（清空 + 灯光 + 材质）
        2. 逐条执行建模和后处理命令
        3. 返回结果列表

        每步命令通过 _generate_bpy_for_command 生成独立 bpy 代码片段，
        经 validate_params 净化参数后，通过 TCP 发送至 Blender MCP Add-on。
        """
        # === 场景初始化（与 Background 模式对齐） ===
        print("[MCPBlenderTool] 初始化场景 (灯光 + 材质) ...")
        setup_resp = self._send_and_recv({
            "type": "execute_code",
            "params": {"code": self._scene_setup_code()},
        }, timeout=15)
        if setup_resp.get("status") != "success":
            print(f"[MCPBlenderTool] 场景初始化异常: {setup_resp.get('message', 'unknown')}")

        results = []
        for cmd in commands:
            result = self.execute(cmd)
            results.append(result)
            status = "[PASS] " if result.success else "[FAIL] "
            print(f"[MCPBlenderTool] {status} step {cmd.step_id}: "
                  f"{cmd.operation} → {result.message}")

        summary_resp = self._send_and_recv({
            "type": "execute_code",
            "params": {"code": self._scene_summary_code()},
        }, timeout=15)
        if summary_resp.get("status") == "success":
            result_text = summary_resp.get("result", {}).get("result", "")
            for line in result_text.split("\n"):
                if line.startswith("SCENE_SUMMARY:"):
                    try:
                        scene_summary = json.loads(line.split(":", 1)[1])
                    except json.JSONDecodeError:
                        scene_summary = None
                    if scene_summary is not None:
                        for r in results:
                            r.output = {"scene_summary": scene_summary}
                    break
        return results

    def render_viewport(
        self, output_path: str, camera_pos: tuple = (5, -5, 3)
    ) -> str | None:
        return None
