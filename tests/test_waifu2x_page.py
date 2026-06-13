# tests/test_waifu2x_page.py
import inspect

import gradio as gr


class TestWaifu2xPage:
    """waifu2x WebUI 页面结构测试。"""

    def test_module_imports(self):
        """页面模块可被导入。"""
        from webui.pages import waifu2x
        assert hasattr(waifu2x, "create_page")

    def test_app_imports_waifu2x_page(self):
        """webui/app.py 导入并挂载 waifu2x 页面。"""
        import webui.app as app_module
        source = inspect.getsource(app_module)
        assert "import waifu2x" in source or "from webui.pages import" in source
        assert "waifu2x.create_page" in source
        assert '"Waifu2x"' in source

    def test_create_page_signature(self):
        """create_page 接受 Gradio State 参数。"""
        from webui.pages.waifu2x import create_page
        sig = inspect.signature(create_page)
        assert "app_state" in sig.parameters
        assert sig.parameters["app_state"].annotation == gr.State
