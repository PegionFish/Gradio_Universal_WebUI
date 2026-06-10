# webui/components/service_table.py — 服务状态表组件

import gradio as gr

STATUS_ICONS = {
    "running": "🟢",
    "unhealthy": "🟡",
    "starting": "🔵",
    "stopped": "⚪",
    "exited": "🔴",
    "stopping": "🔵",
}

STATUS_LABELS = {
    "running": "运行中",
    "unhealthy": "不健康",
    "starting": "启动中",
    "stopped": "已停止",
    "exited": "已退出",
    "stopping": "停止中",
}


def build_service_table_html(svc_list: list[dict]) -> str:
    """从服务字典列表构建 HTML 表格。

    Args:
        svc_list: 服务字典列表，每个字典包含 id/display_name/model_type/
                  runtime_state/gpu_assignment/service_url

    Returns:
        HTML 表格字符串
    """
    if not svc_list:
        return "<p style='color:#888'>暂无服务配置。请前往<em>配置</em>标签页添加服务。</p>"

    lines = [
        "<table class='service-table' style='width:100%;border-collapse:collapse;"
        "font-size:14px'>",
        "<thead><tr style='background:#f5f5f5'>",
        "<th style='padding:8px;text-align:left'>ID</th>",
        "<th style='padding:8px;text-align:left'>名称</th>",
        "<th style='padding:8px;text-align:left'>类型</th>",
        "<th style='padding:8px;text-align:left'>状态</th>",
        "<th style='padding:8px;text-align:left'>GPU</th>",
        "<th style='padding:8px;text-align:left'>URL</th>",
        "</tr></thead><tbody>",
    ]

    for s in svc_list:
        state = s.get("runtime_state", "stopped")
        icon = STATUS_ICONS.get(state, "⚪")
        label = STATUS_LABELS.get(state, state)
        gpu_list = s.get("gpu_assignment", []) or []
        gpu_str = ",".join(map(str, gpu_list)) if gpu_list else "不限"
        url_str = s.get("service_url", "") or "(未配置)"

        row_color = {
            "running": "#e8f5e9", "unhealthy": "#fff3e0",
        }.get(state, "transparent")

        lines.append(
            f"<tr style='background:{row_color}'>"
            f"<td style='padding:6px 8px;font-family:monospace'>{s.get('id', '')}</td>"
            f"<td style='padding:6px 8px'>{s.get('display_name', '')}</td>"
            f"<td style='padding:6px 8px'>{s.get('model_type', '')}</td>"
            f"<td style='padding:6px 8px'>{icon} {label}</td>"
            f"<td style='padding:6px 8px'>{gpu_str}</td>"
            f"<td style='padding:6px 8px;font-family:monospace;font-size:12px'>{url_str}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table>")
    return "".join(lines)


def render_service_controls():
    """渲染服务控制区域（选择器 + 启动/停止/重启按钮）。

    Returns:
        (service_selector, btn_start, btn_stop, btn_restart, status_msg, log_viewer,
         confirm_stop_html, btn_confirm_stop, btn_cancel_stop)
    """
    with gr.Row():
        service_selector = gr.Dropdown(
            label="选择服务", choices=[], interactive=True, scale=2,
        )
        btn_start = gr.Button("启动", variant="primary", scale=1, min_width=80)
        btn_stop = gr.Button("停止", variant="stop", scale=1, min_width=80)
        btn_restart = gr.Button("重启", variant="secondary", scale=1, min_width=80)

    confirm_stop_html = gr.HTML(visible=False)
    with gr.Row():
        btn_confirm_stop = gr.Button(
            "确认停止", variant="stop", visible=False, scale=1,
        )
        btn_cancel_stop = gr.Button(
            "取消", variant="secondary", visible=False, scale=1,
        )

    status_msg = gr.Textbox(label="操作结果", interactive=False)
    log_viewer = gr.Textbox(
        label="日志 (最后 50 行)", lines=10, interactive=False,
    )

    return (
        service_selector, btn_start, btn_stop, btn_restart,
        status_msg, log_viewer,
        confirm_stop_html, btn_confirm_stop, btn_cancel_stop,
    )
