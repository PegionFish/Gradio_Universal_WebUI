# 模块 9：WebUI 主程序组装

## 用途

组装 Gradio `gr.Blocks` 应用，整合所有页面标签页、共享状态和组件。充当 WebUI 的入口点，被 `main.py` 调用。

## 依赖

- **所有上方模块**：核心服务、适配器、日志
- Python 包：`gradio>=5.0`

## 状态架构（核心设计）

多标签页切换时状态不丢失的关键在于**三层状态分离**：

```text
┌──────────────────────────────────────────────────────────────┐
│ Layer 3: Gradio 组件值（文本框内容、滑块值、下拉选择...）     │
│          每个标签页独立，Gradio 用 display:none 保留 DOM，     │
│          切换回来时组件值完整保持                               │
├──────────────────────────────────────────────────────────────┤
│ Layer 2: gr.State 组件（在 gr.Blocks 顶层创建）              │
│          跨标签页共享的 UI 级状态，如当前选中的服务 ID、       │
│          最后一次拉取的数据快照                                 │
├──────────────────────────────────────────────────────────────┤
│ Layer 1: core/ 模块级变量（Python 进程内存）                  │
│          所有真相来源——ServiceRegistry、GpuSnapshot、          │
│          SQLite 数据库。后台守护线程持续更新，                 │
│          完全不受 UI 标签页切换影响                            │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ HealthChecker → registry.set_runtime_state()          │    │
│  │ GpuMonitor   → self._latest (GpuSnapshot)            │    │
│  │ ProcessManager → registry.set_runtime_state()        │    │
│  │ TaskScheduler → SQLite (持久化)                      │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**核心原则：**

1. **所有后台服务以守护线程运行，与 UI 完全解耦。** HealthChecker 每 10 秒探测服务、GpuMonitor 每 5 秒采集指标，即使浏览器关闭也在运行。
2. **UI 只是 Layer 1 的观察者。** 标签页切换时，页面函数从 Layer 1 重新读取最新数据渲染到 `gr.HTML` 组件中。
3. **用户输入（表单、下拉框、滑块）由 Gradio 自动保持。** 标签页切换使用 CSS `display:none` 而非 DOM 卸载，组件值完整保留。
4. **`gr.Timer` 只在当前激活的标签页触发。** 不激活的标签页中的 `gr.Timer` 回调不会被调用。因此数据刷新不能依赖页面内的 `gr.Timer`，而是通过顶层统一刷新 + 标签切换时主动拉取的组合策略。

### 刷新策略

```text
顶层 gr.Timer (5秒)
  │
  ├── 从 Layer 1 读取最新数据
  │   ├── registry.list_services()
  │   ├── gpu_monitor.get_latest()
  │   └── scheduler.list_tasks(limit=5)
  │
  └── 写入 Layer 2 (gr.State)
       └── 顶层 state 字典更新

gr.Tabs 的 .change() 事件
  │
  └── 当用户切换到某个标签页时触发
      ├── 从 Layer 2 (gr.State) 读取最新快照
      └── 更新该标签页的 gr.HTML 组件
          （使用 gr.update(value=html)）

页面内的 gr.Timer
  │
  └── 仅在该标签页激活时有效
      用于激活时自动刷新的场景
      切换离开后自动暂停
```

## app.py

### 文件位置

`webui/app.py`

### create_app()

```python
import gradio as gr
from webui import pages
from core import registry, scheduler, gpu_monitor
import json


CSS = """
.gradio-container {max-width: none !important;}
footer {display: none !important;}
"""


def create_app() -> gr.Blocks:
    """组装 Gradio 应用。
    
    状态架构：
    - 顶层 gr.State 存放所有跨标签页共享的数据快照
    - 顶层 gr.Timer 驱动全局数据刷新（仅激活的标签页有效，但足够）
    - gr.TabItem 切换时通过 .select() 事件拉取最新数据
    - 每个标签页内独立布局，通过 gr.HTML 展示动态数据
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
        
        # ── 顶层共享状态（Layer 2）──
        # 对字典的字段赋值不需要触发 Gradio 响应式更新，
        # 该 state 仅作为标签页切换时的数据中转站。
        app_state = gr.State({
            "services": [],
            "tasks": [],
            "gpu_metrics": {"available": False, "snapshots": [], "updated_at": ""},
            "last_refresh": "",
        })
        
        # ── 顶层定时刷新（每 5 秒更新 app_state）──
        def refresh_global_state():
            svc_list = registry.list_services()
            svc_data = [
                {"id": s.id, "display_name": s.display_name,
                 "model_type": s.model_type, "runtime_state": s.runtime_state,
                 "gpu_assignment": s.gpu_assignment, "service_url": s.service_url}
                for s in svc_list
            ]
            task_data = [
                {"id": t["id"], "service_id": t["service_id"],
                 "model_type": t["model_type"], "status": t["status"],
                 "created_at": t["created_at"][:19],
                 "error_summary": (t.get("error_summary") or "")[:40]}
                for t in scheduler.list_tasks(limit=5)
            ]
            gpu = gpu_monitor.get_latest()
            gpu_data = {
                "available": gpu.available,
                "snapshots": [
                    {"gpu_index": s.gpu_index, "name": s.name,
                     "memory_total_mb": s.memory_total_mb,
                     "memory_used_mb": s.memory_used_mb,
                     "memory_free_mb": s.memory_free_mb,
                     "utilization_percent": s.utilization_percent,
                     "temperature_celsius": s.temperature_celsius,
                     "power_milliwatts": s.power_milliwatts,
                     "processes": s.processes}
                    for s in gpu.snapshots
                ],
                "updated_at": gpu.updated_at,
            }
            
            return {
                "services": svc_data,
                "tasks": task_data,
                "gpu_metrics": gpu_data,
                "last_refresh": __import__("datetime").datetime.now().strftime("%H:%M:%S"),
            }
        
        # ── app_state 定时更新 ──
        # 注意：此 Timer 只在用户停留在任意标签页时触发。
        # 但它写入的 app_state 在所有标签页间共享，
        # 切换标签页时通过 .select() 读取最新 app_state。
        refresh_timer = gr.Timer(value=5)
        refresh_timer.tick(refresh_global_state, outputs=app_state)
        
        # ── 标签页结构 ──
        with gr.Tabs(elem_id="main-tabs"):
            
            # 仪表盘
            with gr.TabItem("仪表盘", elem_id="tab-dashboard", id="dashboard"):
                dashboard_html = pages.dashboard.create_page(app_state)
            
            # 服务管理
            with gr.TabItem("服务管理", elem_id="tab-services", id="services"):
                services_block = pages.services.create_page(app_state)
            
            # 任务管理
            with gr.TabItem("任务管理", elem_id="tab-tasks", id="tasks"):
                tasks_block = pages.tasks.create_page(app_state)
            
            # GPU 监控
            with gr.TabItem("GPU 监控", elem_id="tab-gpu", id="gpu"):
                gpu_block = pages.gpu.create_page(app_state)
            
            # 配置
            with gr.TabItem("配置", elem_id="tab-config", id="config"):
                config_block = pages.config.create_page(app_state)
            
            # 模型入口标签页（占位）
            with gr.TabItem("Stable Diffusion", elem_id="tab-sd", id="sd"):
                sd_block = pages.stable_diffusion.create_page(app_state)
            
            with gr.TabItem("Qwen3 ASR", elem_id="tab-qwen3", id="qwen3"):
                qwen3_block = pages.qwen3_asr.create_page(app_state)
            
            with gr.TabItem("WhisperX", elem_id="tab-whisperx", id="whisperx"):
                whisperx_block = pages.whisperx.create_page(app_state)
            
            with gr.TabItem("FastWhisper", elem_id="tab-fastwhisper", id="fastwhisper"):
                fastwhisper_block = pages.fastwhisper.create_page(app_state)
        
        # ── 标签页切换时刷新对应内容 ──
        # 当用户切换到某个标签页时，从 app_state 读取最新数据渲染
        # 这样即使用户长时间停留在标签页 A，切换到 B 时 B 总是看到最新状态
        
        def on_tab_dashboard_select(state):
            return _render_dashboard(state)
        
        def on_tab_services_select(state):
            return _render_service_table(state)
        
        def on_tab_tasks_select(state):
            return _render_task_list(state)
        
        def on_tab_gpu_select(state):
            return _render_gpu_dashboard(state)
        
        app.load(_render_dashboard, inputs=app_state, outputs=dashboard_html)
        
        # 注意：Gradio 的 .select() 事件需要绑定到 gr.TabItem
        # 这里需要在各个页面组件上绑定 .select 事件
        # 具体实现见页面文件中 tab_select_callback 的注册
    
    return app


# ── 渲染辅助函数（从 app_state 构建 HTML）──

def _render_dashboard(state):
    """从 state 构建仪表盘 HTML。"""
    services = state["services"]
    tasks = state["tasks"]
    gpu = state["gpu_metrics"]
    
    running = sum(1 for s in services if s["runtime_state"] == "running")
    total = len(services)
    
    parts = [f"<h3>概览</h3>"]
    parts.append(f"<p><b>{running}/{total}</b> 个服务正在运行 | 刷新于 {state['last_refresh']}</p>")
    
    # 服务状态
    parts.append("<h4>服务状态</h4><ul>")
    for s in services:
        icon = {"running": "🟢", "unhealthy": "🟡", "starting": "🔵",
                "stopped": "⚪", "exited": "🔴"}.get(s["runtime_state"], "⚪")
        parts.append(f"<li>{icon} {s['display_name']} — {s['runtime_state']}</li>")
    parts.append("</ul>")
    
    # 最近任务
    parts.append("<h4>最近任务</h4>")
    if tasks:
        parts.append("<table border='1' cellpadding='4' style='border-collapse:collapse'><tr><th>ID</th><th>服务</th><th>状态</th></tr>")
        for t in tasks:
            parts.append(f"<tr><td>{t['id'][:8]}...</td><td>{t['service_id']}</td><td>{t['status']}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p>暂无任务</p>")
    
    # GPU
    parts.append("<h4>GPU</h4>")
    if gpu["available"]:
        for s in gpu["snapshots"]:
            mem_pct = int(s["memory_used_mb"] / max(s["memory_total_mb"], 1) * 100)
            parts.append(
                f"<p>GPU {s['gpu_index']}: {s['name']} — "
                f"{s['memory_used_mb']}/{s['memory_total_mb']} MiB ({mem_pct}%) — "
                f"{s['utilization_percent']}% — {s['temperature_celsius']}°C</p>"
            )
    else:
        parts.append("<p>未检测到 NVIDIA GPU。</p>")
    
    return gr.update(value="".join(parts))


def _render_service_table(state):
    """从 state 构建服务状态表 HTML。"""
    services = state["services"]
    lines = ["<table border='1' cellpadding='6' style='border-collapse:collapse; width:100%'>",
             "<tr><th>ID</th><th>名称</th><th>类型</th><th>状态</th><th>GPU</th><th>URL</th></tr>"]
    for s in services:
        status_display = {
            "running": "🟢 运行中", "stopped": "⚪ 已停止",
            "starting": "🔵 启动中", "unhealthy": "🟡 不健康",
            "stopping": "🔵 停止中", "exited": "🔴 已退出",
        }.get(s["runtime_state"], s["runtime_state"])
        gpu_str = ",".join(map(str, s["gpu_assignment"])) if s["gpu_assignment"] else "不限"
        url_str = s["service_url"] or "(未配置)"
        lines.append(f"<tr><td>{s['id']}</td><td>{s['display_name']}</td>"
                     f"<td>{s['model_type']}</td><td>{status_display}</td>"
                     f"<td>{gpu_str}</td><td>{url_str}</td></tr>")
    lines.append("</table>")
    lines.append(f"<p style='color:#888;font-size:12px'>刷新于 {state['last_refresh']}</p>")
    return gr.update(value="".join(lines))


def _render_task_list(state):
    """从 state 构建任务列表 HTML。"""
    tasks = state["tasks"]
    if not tasks:
        return gr.update(value="<p>暂无任务</p>")
    lines = ["<table border='1' cellpadding='4' style='border-collapse:collapse; width:100%'>",
             "<tr><th>ID</th><th>服务</th><th>模型</th><th>状态</th><th>时间</th><th>错误</th></tr>"]
    for t in tasks:
        lines.append(f"<tr><td>{t['id'][:8]}...</td><td>{t['service_id']}</td>"
                     f"<td>{t['model_type']}</td><td>{t['status']}</td>"
                     f"<td>{t['created_at']}</td>"
                     f"<td style='color:red'>{t['error_summary']}</td></tr>")
    lines.append("</table>")
    return gr.update(value="".join(lines))


def _render_gpu_dashboard(state):
    """从 state 构建 GPU 仪表盘 HTML。"""
    gpu = state["gpu_metrics"]
    if not gpu["available"]:
        return gr.update(value="<div style='padding:20px;text-align:center;color:#888'>"
                               "<h3>未检测到 NVIDIA GPU</h3></div>")
    
    cards = []
    for s in gpu["snapshots"]:
        mem_pct = int(s["memory_used_mb"] / max(s["memory_total_mb"], 1) * 100)
        cards.append(
            f"<div style='border:1px solid #ddd;border-radius:8px;padding:12px;margin:8px;"
            f"background:#f9f9f9;width:30%;min-width:280px;display:inline-block;vertical-align:top;'>"
            f"<h4>GPU {s['gpu_index']}: {s['name']}</h4>"
            f"<table style='width:100%'>"
            f"<tr><td>显存</td><td>{s['memory_used_mb']}/{s['memory_total_mb']} MiB ({mem_pct}%)</td></tr>"
            f"<tr><td>利用率</td><td>{s['utilization_percent']}%</td></tr>"
            f"<tr><td>温度</td><td>{s['temperature_celsius']}°C</td></tr>"
            f"<tr><td>进程</td><td>{len(s['processes'])}</td></tr>"
            f"</table></div>"
        )
    return gr.update(value="".join(cards) + f"<p style='color:#888'>更新于 {gpu['updated_at'][:19]}</p>")


def launch_app(app: gr.Blocks, host: str = "0.0.0.0", port: int = 7860):
    """启动 Gradio 应用。阻塞直到用户 Ctrl+C。"""
    app.queue(default_concurrency_limit=16).launch(
        server_name=host,
        server_port=port,
        share=False,
        show_error=True,
    )
```

## state.py

### 文件位置

`webui/state.py`

### AppState 类

```python
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


# 全局单例（在 app.py 中初始化）
instance: AppState | None = None


def init():
    global instance
    instance = AppState()


def get() -> AppState:
    assert instance is not None, "AppState 未初始化"
    return instance
```

## 页面接口约定

每个 `pages/*.py` 文件导出一个 `create_page(app_state)` 函数：

```python
# pages/xxx.py 的约定结构
def create_page(app_state: gr.State) -> gr.HTML:
    """创建标签页内容。
    
    参数:
        app_state: 顶层 gr.State，包含 services/tasks/gpu_metrics 数据
    
    返回:
        页面的主输出组件（通常是 gr.HTML，通过 gr.update 刷新）
    """
    with gr.Blocks() as page:
        # 页面内容
        main_output = gr.HTML("加载中...")
        # ... 其他组件 ...
    
    # 将 main_output 注册到 app.py 的全局刷新中
    return main_output
```

## 页面注册与导入

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

app = create_app()
host = args.host or config.get_server_setting("host", "0.0.0.0")
port = args.port or config.get_server_setting("port", 7860)
launch_app(app, host=host, port=port)
```

## 验收标准

1. `create_app()` 返回 `gr.Blocks` 实例，顶层包含 `gr.Timer` 和 `gr.State`
2. 所有 9 个标签页显示在 UI 中
3. 切换到仪表盘标签页时，显示最新的服务状态、任务和 GPU 数据
4. 在标签页 A 停留 30 秒后切换到标签页 B，B 显示的数据是 5 秒内最新的（由顶层 Timer 保证）
5. 表单输入（在模型入口页面填写的文本框、下拉框、滑块值）在切换标签页后保持
6. 后台服务（HealthChecker, GpuMonitor）在浏览器切换标签页时继续运行
7. `app.queue(16)` 启用并发队列
