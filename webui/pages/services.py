# webui/pages/services.py — 服务管理页面

import gradio as gr
from core import registry, process_manager, scheduler


def create_page(app_state: gr.State) -> gr.HTML:
    """创建服务管理标签页。"""
    gr.Markdown("## 服务管理")

    # 服务状态表（由顶层刷新）
    service_table = gr.HTML("加载中...")

    gr.Markdown("---")
    gr.Markdown("### 服务控制")

    with gr.Row():
        service_selector = gr.Dropdown(
            label="选择服务",
            choices=[],
            interactive=True,
            scale=2,
        )
        btn_start = gr.Button("启动", variant="primary", scale=1, min_width=80)
        btn_stop = gr.Button("停止", variant="stop", scale=1, min_width=80)
        btn_restart = gr.Button("重启", variant="secondary", scale=1, min_width=80)

    # 停止确认对话框（默认隐藏）
    confirm_stop_html = gr.HTML(visible=False)
    with gr.Row():
        btn_confirm_stop = gr.Button(
            "确认停止", variant="stop", visible=False, scale=1
        )
        btn_cancel_stop = gr.Button(
            "取消", variant="secondary", visible=False, scale=1
        )

    status_msg = gr.Textbox(label="操作结果", interactive=False)

    gr.Markdown("---")
    gr.Markdown("### 服务日志")
    log_viewer = gr.Textbox(
        label="日志 (最后 50 行)", lines=10, interactive=False
    )

    # ── 从 app_state 刷新服务表 ──
    def refresh_from_state(state):
        svc_list = state.get("services", [])
        html = _build_service_table(svc_list)
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

    # 选择服务时自动加载日志
    service_selector.change(
        fn=_on_select_service,
        inputs=service_selector,
        outputs=log_viewer,
    )

    return service_table


def _build_service_table(svc_list):
    lines = [
        "<table border='1' cellpadding='6' "
        "style='border-collapse:collapse; width:100%'>",
        "<tr><th>ID</th><th>名称</th><th>类型</th>"
        "<th>状态</th><th>GPU</th><th>URL</th></tr>",
    ]
    status_map = {
        "running": "🟢 运行中", "stopped": "⚪ 已停止",
        "starting": "🔵 启动中", "unhealthy": "🟡 不健康",
        "stopping": "🔵 停止中", "exited": "🔴 已退出",
    }
    for s in svc_list:
        status_display = status_map.get(
            s.get("runtime_state", ""), s.get("runtime_state", "")
        )
        gpu_list = s.get("gpu_assignment", []) or []
        gpu_str = ",".join(map(str, gpu_list)) if gpu_list else "不限"
        url_str = s.get("service_url", "") or "(未配置)"
        lines.append(
            f"<tr><td>{s.get('id', '')}</td>"
            f"<td>{s.get('display_name', '')}</td>"
            f"<td>{s.get('model_type', '')}</td>"
            f"<td>{status_display}</td>"
            f"<td>{gpu_str}</td><td>{url_str}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _on_service_action(service_id: str, action: str):
    if not service_id:
        return "请先选择一个服务"
    getattr(process_manager, action)(service_id)
    return f"已提交 {action} 请求: {service_id}"


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
                value=f"<div style='color:orange'>⚠️ 服务 {service_id} 有 "
                f"{len(running_tasks)} 个运行中的任务。停止将中断这些任务。</div>",
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
            f"已提交停止请求: {service_id}",
            gr.update(visible=False),
            gr.update(visible=False),
        ]


def _on_select_service(service_id: str):
    if not service_id:
        return "(选择服务后查看日志)"
    log = process_manager.tail_log(service_id)
    return log
