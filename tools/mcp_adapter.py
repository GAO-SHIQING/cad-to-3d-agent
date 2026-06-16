"""MCPBlenderTool — TCP Socket communication with Blender MCP Add-on

Requires: blender-mcp (ahujasid/blender-mcp)
The Blender add-on must be installed and running before use.
"""

import json
import socket
from typing import List
from .blender_tool import BlenderTool, BlenderCommand, BlenderResult


class MCPBlenderTool(BlenderTool):
    """MCP mode: TCP Socket → Blender Add-on"""

    def __init__(self, host: str = "localhost", port: int = 9876):
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._connected = False

    def connect(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(5)
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

    def _send_command(self, operation: str, params: dict) -> dict:
        """Send JSON command and receive response"""
        if not self._sock or not self._connected:
            return {"success": False, "error": "Not connected"}

        request = json.dumps({
            "command": operation,
            "params": params,
        })
        self._sock.sendall(request.encode() + b"\n")

        response_data = b""
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            if b"\n" in response_data:
                break

        return json.loads(response_data.decode().strip())

    def execute(self, command: BlenderCommand) -> BlenderResult:
        try:
            resp = self._send_command(command.operation, command.params)
            return BlenderResult(
                success=resp.get("success", False),
                step_id=command.step_id,
                message=resp.get("message", resp.get("error", "")),
                output=resp,
            )
        except Exception as e:
            return BlenderResult(
                success=False, step_id=command.step_id, message=str(e)
            )

    def execute_batch(
        self, commands: List[BlenderCommand]
    ) -> List[BlenderResult]:
        results = []
        for cmd in commands:
            result = self.execute(cmd)
            results.append(result)
            if not result.success:
                print(f"[MCPBlenderTool] Step {cmd.step_id} failed: {result.message}")
        return results

    def render_viewport(
        self, output_path: str, camera_pos: tuple = (5, -5, 3)
    ) -> str | None:
        try:
            resp = self._send_command("render", {
                "camera_pos": camera_pos,
                "output_path": output_path,
            })
            if resp.get("success"):
                return output_path
        except Exception as e:
            print(f"[MCPBlenderTool] Render failed: {e}")
        return None
