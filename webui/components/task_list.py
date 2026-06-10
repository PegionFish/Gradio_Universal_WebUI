# webui/components/task_list.py — 任务列表和筛选组件

import gradio as gr

STATUS_COLORS = {
    "queued": "#4a90d9",
    "running": "#f0a500",
    "completed": "#4caf50",
    "failed": "#e74c3c",
    "cancelled": "#95a5a6",
}

STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def build_task_list_html(tasks: list[dict]) -> str:
    """从任务字典列表构建 HTML 表格。

    Args:
        tasks: 任务字典列表（来自 SQLite Row）

    Returns:
        HTML 表格字符串；若无任务则返回空状态提示。
    """
    if not tasks:
        return (
            "<div style='text-align:center;padding:32px;color:#888'>"
            "<p style='font-size:32px'>📋</p>"
            "<p>暂无任务</p>"
            "<p style='font-size:12px'>提交模型推理任务后将在此处显示</p>"
            "</div>"
        )

    lines = [
        "<table style='width:100%;border-collapse:collapse;font-size:13px'>",
        "<thead><tr style='background:#f5f5f5'>",
        "<th style='padding:8px;text-align:left'>任务 ID</th>",
        "<th style='padding:8px;text-align:left'>服务</th>",
        "<th style='padding:8px;text-align:left'>模型</th>",
        "<th style='padding:8px;text-align:left'>状态</th>",
        "<th style='padding:8px;text-align:left'>创建时间</th>",
        "<th style='padding:8px;text-align:left'>错误</th>",
        "</tr></thead><tbody>",
    ]

    for t in tasks:
        status = t.get("status", "queued")
        color = STATUS_COLORS.get(status, "#888")
        label = STATUS_LABELS.get(status, status)
        error = t.get("error_summary", "") or ""
        created = t.get("created_at", "")[:19]

        lines.append(
            f"<tr>"
            f"<td style='padding:6px 8px;font-family:monospace;font-size:11px'>"
            f"{t.get('id', '')[:8]}...</td>"
            f"<td style='padding:6px 8px'>{t.get('service_id', '')}</td>"
            f"<td style='padding:6px 8px'>{t.get('model_type', '')}</td>"
            f"<td style='padding:6px 8px'>"
            f"<span style='color:{color};font-weight:600'>{label}</span></td>"
            f"<td style='padding:6px 8px;font-size:12px'>{created}</td>"
            f"<td style='padding:6px 8px;color:red;font-size:12px;"
            f"max-width:200px;overflow:hidden'>{error[:50]}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table>")
    return "".join(lines)


def render_task_filters():
    """渲染任务筛选控件。

    Returns:
        (filter_service, filter_status, btn_refresh)
    """
    with gr.Row():
        filter_service = gr.Dropdown(
            label="筛选服务", choices=[], interactive=True, scale=1,
        )
        filter_status = gr.Dropdown(
            label="筛选状态",
            choices=["全部", "queued", "running", "completed", "failed", "cancelled"],
            value="全部",
            interactive=True,
            scale=1,
        )
        btn_refresh = gr.Button("刷新", variant="secondary", scale=0)
    return filter_service, filter_status, btn_refresh
