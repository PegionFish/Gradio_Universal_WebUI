# webui/pages/services.py — 服务管理页面

import gradio as gr
from core import registry, process_manager, scheduler
from webui.components.service_table import build_service_table_html
from webui.components.error_display import format_error_message


def create_page(app_state: gr.State) -> gr.HTML:
    """创建服务管理标签页。"""
    gr.Markdown("## 服务管理")

    # ── 服务状态表（由顶层刷新）──
    service_table = gr.HTML("加载中...")

    gr.Markdown("---")
    gr.Markdown("### 服务控制")

    with gr.Row():
        service_selector = gr.Dropdown(
            label="选择服务", choices=[], interactive=True, scale=2,
        )
        btn_start = gr.Button("▶ 启动", variant="primary", scale=1, min_width=80)
        btn_stop = gr.Button("⏹ 停止", variant="stop", scale=1, min_width=80)
        btn_restart = gr.Button("🔄 重启", variant="secondary", scale=1, min_width=80)

    confirm_stop_html = gr.HTML(visible=False)
    with gr.Row():
        btn_confirm_stop = gr.Button(
            "⚠️ 确认停止", variant="stop", visible=False, scale=1,
        )
        btn_cancel_stop = gr.Button(
            "取消", variant="secondary", visible=False, scale=1,
        )

    status_msg = gr.Textbox(label="操作结果", interactive=False)

    # ── 日志查看（带自动刷新）──
    gr.Markdown("---")
    gr.Markdown("### 服务日志")

    with gr.Row():
        log_info = gr.Markdown("")
        log_auto_refresh = gr.Checkbox(
            label="自动刷新 (2s)", value=False, scale=0,
        )

    log_viewer = gr.Textbox(
        label="日志 (最后 50 行)", lines=12, interactive=False,
        max_lines=20,
    )

    # 日志自动刷新 Timer
    log_timer = gr.Timer(value=2)

    # ── 从 app_state 刷新服务表 ──
    def refresh_from_state(state):
        svc_list = state.get("services", [])
        html = build_service_table_html(svc_list)
        choices = [
            (s.get("display_name", s.get("id", "")), s.get("id", ""))
            for s in svc_list
        ]
        return gr.update(value=html), gr.update(choices=choices)

    service_table.select(
        refresh_from_state,
        inputs=app_state,
        outputs=[service_table, service_selector],
    )

    # ── 按钮回调 ──
    btn_start.click(
        fn=lambda sid: _on_service_action(sid, "start"),
        inputs=service_selector,
        outputs=status_msg,
    )

    btn_stop.click(
        fn=_on_stop_click,
        inputs=service_selector,
        outputs=[
            confirm_stop_html, status_msg, btn_confirm_stop, btn_cancel_stop,
        ],
    )

    btn_confirm_stop.click(
        fn=lambda sid: _on_service_action(sid, "stop"),
        inputs=service_selector,
        outputs=status_msg,
    ).then(
        fn=lambda: (
            gr.update(visible=False), gr.update(visible=False),
            gr.update(visible=False),
        ),
        outputs=[confirm_stop_html, btn_confirm_stop, btn_cancel_stop],
    )

    btn_cancel_stop.click(
        fn=lambda: (
            gr.update(visible=False), "",
            gr.update(visible=False), gr.update(visible=False),
        ),
        outputs=[confirm_stop_html, status_msg, btn_confirm_stop, btn_cancel_stop],
    )

    btn_restart.click(
        fn=lambda sid: _on_service_action(sid, "restart"),
        inputs=service_selector,
        outputs=status_msg,
    )

    # ── 选择服务时加载日志 ──
    def on_select_service(service_id):
        if not service_id:
            return "(选择服务后查看日志)", ""
        log = process_manager.tail_log(service_id, lines=50)

        # 获取日志文件信息
        files = process_manager.list_log_files(service_id)
        if files:
            latest = files[0]
            info = (
                f"📄 {latest['filename']} | "
                f"{latest['lines']} 行 | "
                f"最后更新: {latest['modified'][:19]}"
            )
        else:
            info = "*(无日志文件)*"
        return log, info

    service_selector.change(
        fn=on_select_service,
        inputs=service_selector,
        outputs=[log_viewer, log_info],
    )

    # ── 日志自动刷新 ──
    def refresh_log(service_id, auto_refresh):
        if not auto_refresh or not service_id:
            return gr.update(), gr.update()
        log = process_manager.tail_log(service_id, lines=50)
        files = process_manager.list_log_files(service_id)
        if files:
            info = f"🔄 自动刷新中 | 📄 {files[0]['filename']} | {files[0]['lines']} 行"
        else:
            info = "🔄 自动刷新中 | *(无日志文件)*"
        return log, info

    log_timer.tick(
        fn=refresh_log,
        inputs=[service_selector, log_auto_refresh],
        outputs=[log_viewer, log_info],
    )

    return service_table


def _on_service_action(service_id: str, action: str):
    if not service_id:
        return "请先选择一个服务"
    getattr(process_manager, action)(service_id)
    return f"✅ 已提交 {action} 请求: {service_id}"


def _on_stop_click(service_id: str):
    if not service_id:
        return [
            gr.update(visible=False), "请先选择一个服务",
            gr.update(visible=False), gr.update(visible=False),
        ]

    running_tasks = scheduler.get_running_tasks(service_id)
    if running_tasks:
        return [
            gr.update(
                value=format_error_message(
                    f"服务有 {len(running_tasks)} 个运行中的任务",
                    service_id=service_id,
                    suggestion="停止将中断这些任务。请确认后再操作。",
                ),
                visible=True,
            ),
            "",
            gr.update(visible=True),
            gr.update(visible=True),
        ]
    else:
        _on_service_action(service_id, "stop")
        return [
            gr.update(visible=False),
            f"✅ 已提交停止请求: {service_id}",
            gr.update(visible=False),
            gr.update(visible=False),
        ]
