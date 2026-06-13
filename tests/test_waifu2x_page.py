# tests/test_waifu2x_page.py
import gradio as gr


class TestWaifu2xPage:
    """waifu2x WebUI 页面结构测试。"""

    def test_module_imports(self):
        """页面模块可被导入。"""
        from webui.pages import waifu2x
        assert hasattr(waifu2x, "create_page")

    def test_app_contains_waifu2x_tab(self):
        """主应用包含 waifu2x 标签页。"""
        from webui.app import create_app

        app = create_app()
        labels = [
            getattr(block, "label", "")
            for block in app.blocks.values()
            if hasattr(block, "label")
        ]
        assert "Waifu2x" in labels
