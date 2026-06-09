# 模块 9：WebUI 主程序组装

## 用途

组装 Gradio `gr.Blocks` 应用，整合所有页面标签页、共享状态和组件。充当 WebUI 的入口点，被 `main.py` 调用。

## 依赖

- **所有上方模块**：核心服务、适配器、日志
- Python 包：`gradio>=5.0`

## app.py

### 文件位置

`webui/app.py`

### create_app()

```python
import gradio as gr
from webui import pages
from webui.state import AppState


CSS = """
.gradio-container {max-width: none !important;}
footer {display: none !important;}
"""


def create_app(state: AppState) -> gr.Blocks:
    """组装 Gradio 应用。
    
    采用 sd-webui-aki 的 UI 工厂模式：每个页面文件导出一个 create_page()
    函数返回 gr.Blocks 实例，主程序收集并集中渲染。
    """
    
    with gr.Blocks(
        theme=gr.themes.Soft(
            font=[gr.themes.GoogleFont("Source Sans Pro"), "Arial", "sans-serif"],
        ),
        title="统一 AI WebUI",
        css=CSS,
    ) as app:
        
        gr.Markdown("# 统一 AI WebUI")
        gr.Markdown("一站式管理本地 AI 负载 — 模型服务配置、任务调度、GPU 监控")
        
        with gr.Tabs(elem_id="main-tabs"):
            # ── 主功能标签页 ──
            state.dashboard_outputs = pages.dashboard.create_page().render()
            
            with gr.TabItem("服务管理", elem_id="tab-services", id="services"):
                state.service_outputs = pages.services.create_page().render()
            
            with gr.TabItem("任务管理", elem_id="tab-tasks", id="tasks"):
                state.task_outputs = pages.tasks.create_page().render()
            
            with gr.TabItem("GPU 监控", elem_id="tab-gpu", id="gpu"):
                state.gpu_outputs = pages.gpu.create_page().render()
            
            with gr.TabItem("配置", elem_id="tab-config", id="config"):
                state.config_outputs = pages.config.create_page().render()
            
            # ── 模型入口标签页（占位） ──
            with gr.TabItem("Stable Diffusion", elem_id="tab-sd", id="sd"):
                pages.stable_diffusion.create_page().render()
            
            with gr.TabItem("Qwen3 ASR", elem_id="tab-qwen3", id="qwen3"):
                pages.qwen3_asr.create_page().render()
            
            with gr.TabItem("WhisperX", elem_id="tab-whisperx", id="whisperx"):
                pages.whisperx.create_page().render()
            
            with gr.TabItem("FastWhisper", elem_id="tab-fastwhisper", id="fastwhisper"):
                pages.fastwhisper.create_page().render()
    
    return app


def launch_app(app: gr.Blocks, host: str = "0.0.0.0", port: int = 7860):
    """启动 Gradio 应用。阻塞直到用户 Ctrl+C。"""
    app.queue(default_concurrency_limit=16).launch(
        server_name=host,
        server_port=port,
        share=False,
        show_error=True,
    )
```

### 页面接口约定

每个 `pages/*.py` 文件导出一个 `create_page()` 函数，返回 `gr.Blocks` 实例。

```python
# pages/xxx.py 的约定结构
def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        # 页面内容
        ...
    return page
```

主功能标签页（dashboard/services/tasks/gpu/config）的 `create_page()` 可以接受 `state` 参数，但第一阶段采用简单模式：页面函数通过 `from core import registry, scheduler` 直接引用核心服务。

模型入口标签页（stable_diffusion/qwen3_asr/whisperx/fastwhisper）在 `create_page()` 内部检查适配器状态：

```python
def create_page() -> gr.Blocks:
    from adapters import get_adapter
    
    with gr.Blocks() as page:
        try:
            adapter = get_adapter("stable-diffusion")
            gr.Markdown("Stable Diffusion 适配器已注册。"
                        "配置并启动服务后即可使用。")
            # 渲染提交表单
            ...
        except ValueError:
            gr.Markdown(
                "> **Stable Diffusion 适配器未注册。**"
                "请联系开发者检查适配器模块是否正确加载。"
            )
    return page
```

## state.py

### 文件位置

`webui/state.py`

### AppState 类

```python
from typing import Optional


class AppState:
    """跨标签页共享的应用状态。
    
    与 Gradio 的 gr.State 不同，AppState 是纯 Python 对象，
    不参与 Gradio 的响应式系统。用于在页面间传递后端数据引用。
    """
    
    def __init__(self):
        # 页面输出引用（由 create_app 赋值）
        self.dashboard_outputs = None
        self.service_outputs = None
        self.task_outputs = None
        self.gpu_outputs = None
        self.config_outputs = None
```

> 第一阶段中 AppState 主要用于记录页面输出引用。跨标签页状态共享主要通过 `gr.State` 组件实现（每个页面根据需要自行创建）。

## 页面注册与导入

所有页面通过 `import webui.pages` 自动导入。可以在 `webui/pages/__init__.py` 中显式导入：

```python
# webui/pages/__init__.py
from webui.pages import (
    dashboard,
    services,
    tasks,
    gpu,
    config,
    stable_diffusion,
    qwen3_asr,
    whisperx,
    fastwhisper,
)
```

## 集成点

在 `main.py` 步骤 7 中：

```python
from webui.app import create_app, launch_app
from webui.state import AppState

state = AppState()
app = create_app(state)

host = args.host or config.get_server_setting("host", "0.0.0.0")
port = args.port or config.get_server_setting("port", 7860)

launch_app(app, host=host, port=port)
```

## 验收标准

1. `create_app()` 返回 `gr.Blocks` 实例
2. 所有 9 个标签页（5 个主功能 + 4 个模型入口）出现在 UI 中
3. 模型入口标签页显示"适配器为占位"的提示信息
4. `launch_app()` 启动后可通过浏览器访问
5. CSS 样式正确应用（footer 隐藏、容器宽度无限制）
6. 应用使用 Gradio 5.x 的 `gr.themes.Soft` 主题
7. `app.queue(16)` 启用并发队列
