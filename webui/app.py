# webui/app.py — Gradio 应用主程序组装

import datetime
import gradio as gr
from core import registry, scheduler, gpu_monitor, system_monitor
from webui.pages import (
    dashboard,
    services,
    tasks,
    gpu as gpu_page,
    config,
    system,
    stable_diffusion,
    qwen3_asr,
    whisperx,
    fastwhisper,
)

CSS = """
.gradio-container {max-width: none !important;}
footer {display: none !important;}
"""


def create_app() -> gr.Blocks:
    # 注入 system_monitor 引用到页面
    from webui.pages import system as system_page
    system_page.set_monitor(system_monitor)
    """组装 Gradio 应用。

    状态架构：
    - 顶层 gr.State 存放所有跨标签页共享的数据快照
    - 顶层 gr.Timer 驱动全局数据刷新
    - gr.TabItem 切换时通过 .select() 事件拉取最新数据
    """

    with gr.Blocks(title="统一 AI WebUI") as app:

        gr.Markdown("# 统一 AI WebUI")
        gr.Markdown("一站式管理本地 AI 负载 — 模型服务配置、任务调度、GPU 监控")

        # ── 顶层共享状态（Layer 2）──
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
                {
                    "id": s.id,
                    "display_name": s.display_name,
                    "model_type": s.model_type,
                    "runtime_state": s.runtime_state,
                    "gpu_assignment": s.gpu_assignment,
                    "service_url": s.service_url,
                }
                for s in svc_list
            ]
            task_data = [
                {
                    "id": t["id"],
                    "service_id": t.get("service_id", ""),
                    "model_type": t.get("model_type", ""),
                    "status": t.get("status", ""),
                    "created_at": t.get("created_at", "")[:19],
                    "error_summary": (
                        t.get("error_summary", "") or ""
                    )[:40],
                }
                for t in scheduler.list_tasks(limit=5)
            ]
            gpu = gpu_monitor.get_latest()
            gpu_data = {
                "available": gpu.available,
                "snapshots": [
                    {
                        "gpu_index": s.gpu_index,
                        "name": s.name,
                        "memory_total_mb": s.memory_total_mb,
                        "memory_used_mb": s.memory_used_mb,
                        "memory_free_mb": s.memory_free_mb,
                        "utilization_percent": s.utilization_percent,
                        "temperature_celsius": s.temperature_celsius,
                        "power_milliwatts": s.power_milliwatts,
                        "processes": s.processes,
                    }
                    for s in gpu.snapshots
                ],
                "updated_at": gpu.updated_at,
            }
            return {
                "services": svc_data,
                "tasks": task_data,
                "gpu_metrics": gpu_data,
                "last_refresh": datetime.datetime.now().strftime("%H:%M:%S"),
            }

        refresh_timer = gr.Timer(value=5)
        refresh_timer.tick(refresh_global_state, outputs=app_state)

        # ── 标签页结构（6 个标签页）──
        with gr.Tabs(elem_id="main-tabs"):
            # 仪表盘 = 仪表盘概览 + GPU 监控 + 系统健康
            with gr.TabItem("仪表盘", elem_id="tab-dashboard", id="dashboard"):
                gr.Markdown("## 仪表盘")
                dashboard.create_page(app_state)
                gr.Markdown("---")
                gpu_page.create_page(app_state)
                gr.Markdown("---")
                system.create_page(app_state)

            # 配置 = YAML 编辑器 + 服务管理 + 任务管理
            with gr.TabItem("配置", elem_id="tab-config", id="config"):
                config.create_page(app_state)
                gr.Markdown("---")
                services.create_page(app_state)
                gr.Markdown("---")
                tasks.create_page(app_state)

            # 模型入口页（4 个，不变）
            with gr.TabItem("Stable Diffusion", elem_id="tab-sd", id="sd"):
                stable_diffusion.create_page(app_state)

            with gr.TabItem("Qwen3 ASR", elem_id="tab-qwen3", id="qwen3"):
                qwen3_asr.create_page(app_state)

            with gr.TabItem("WhisperX", elem_id="tab-whisperx", id="whisperx"):
                whisperx.create_page(app_state)

            with gr.TabItem("FastWhisper", elem_id="tab-fastwhisper", id="fastwhisper"):
                fastwhisper.create_page(app_state)

    return app


def launch_app(app: gr.Blocks, host: str = "0.0.0.0", port: int = 7860):
    """启动 Gradio 应用。阻塞直到用户 Ctrl+C。"""
    app.queue(default_concurrency_limit=16).launch(
        server_name=host,
        server_port=port,
        share=False,
        show_error=True,
        theme=gr.themes.Soft(
            font=[gr.themes.GoogleFont("Source Sans Pro"), "Arial", "sans-serif"],
        ),
        css=CSS,
    )
