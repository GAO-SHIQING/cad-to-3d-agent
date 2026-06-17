"""测试 Blender 片段生成层是否可共享。"""


def test_background_script_builder_uses_shared_scene_snippets(monkeypatch):
    import tools.background_adapter as background_adapter

    monkeypatch.setattr(background_adapter, "scene_setup_code", lambda: "SETUP_SENTINEL")
    monkeypatch.setattr(background_adapter, "scene_summary_code", lambda **kwargs: "SUMMARY_SENTINEL")

    script = background_adapter.build_script_content(
        commands_json='[]',
        output_blend='/tmp/model.blend',
        output_dir='/tmp/output',
    )

    assert "SETUP_SENTINEL" in script
    assert "SUMMARY_SENTINEL" in script


def test_mcp_scene_helpers_delegate_to_shared_snippets(monkeypatch):
    import tools.mcp_adapter as mcp_adapter

    monkeypatch.setattr(mcp_adapter, "scene_setup_code", lambda: "SETUP_SENTINEL")
    monkeypatch.setattr(mcp_adapter, "scene_summary_code", lambda **kwargs: "SUMMARY_SENTINEL")

    tool = mcp_adapter.MCPBlenderTool()

    assert "SETUP_SENTINEL" in tool._scene_setup_code()
    assert "SUMMARY_SENTINEL" in tool._scene_summary_code()
