# webui/state.py — 模块级单例，记录各标签页输出的组件引用

from typing import Any


class AppState:
    """模块级单例，记录各标签页输出的 gr.HTML 组件引用。

    用于标签页切换时的刷新：当 .select() 事件触发时，
    通过 AppState 获取对应页面的 HTML 输出组件，调用 gr.update()。
    """

    def __init__(self):
        self.dashboard_html: Any = None
        self.service_table_html: Any = None
        self.task_list_html: Any = None
        self.gpu_dashboard_html: Any = None


# 全局单例（在 app.py create_app 中初始化）
instance: AppState | None = None


def init():
    global instance
    instance = AppState()


def get() -> AppState:
    assert instance is not None, "AppState 未初始化"
    return instance
