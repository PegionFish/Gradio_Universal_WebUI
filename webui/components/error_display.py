# webui/components/error_display.py — 错误展示组件

def format_error_message(
    summary: str,
    service_id: str = "",
    task_id: str = "",
    suggestion: str = "",
    details: str = "",
) -> str:
    """格式化用户友好的错误信息。

    Args:
        summary: 简短错误摘要
        service_id: 受影响的服务 ID
        task_id: 受影响的任务 ID
        suggestion: 建议的下一步操作
        details: 详细错误信息（技术细节）

    Returns:
        格式化后的 HTML 字符串
    """
    parts = [
        "<div style='border:1px solid #e74c3c;border-radius:8px;padding:16px;"
        "background:#fdf2f2;margin:12px 0;font-size:14px'>",
        f"<h4 style='color:#c0392b;margin:0 0 8px 0'>⚠️ {summary}</h4>",
    ]

    if service_id:
        parts.append(
            f"<p style='margin:2px 0;color:#555'>"
            f"<b>受影响的服务:</b> <code>{service_id}</code></p>"
        )
    if task_id:
        parts.append(
            f"<p style='margin:2px 0;color:#555'>"
            f"<b>任务 ID:</b> <code>{task_id}</code></p>"
        )
    if suggestion:
        parts.append(
            f"<p style='margin:8px 0;color:#c0392b;font-weight:600'>"
            f"💡 {suggestion}</p>"
        )
    if details:
        parts.append(
            f"<details style='margin-top:8px'>"
            f"<summary style='cursor:pointer;color:#888;font-size:12px'>"
            f"技术详情</summary>"
            f"<pre style='background:#fff;padding:8px;border-radius:4px;"
            f"font-size:11px;overflow-x:auto;margin-top:4px'>{details}</pre>"
            f"</details>"
        )

    parts.append("</div>")
    return "".join(parts)


def render_error_card(message: str, action_required: str = "") -> str:
    """渲染一个简洁的错误卡片。

    Args:
        message: 错误信息
        action_required: 用户需要执行的操作

    Returns:
        HTML 错误卡片
    """
    action_html = (
        f"<p style='margin:4px 0;color:#e67e22'><b>需要操作:</b> {action_required}</p>"
        if action_required else ""
    )
    return (
        "<div style='border-left:4px solid #e74c3c;padding:12px 16px;"
        "background:#fff5f5;border-radius:4px;margin:8px 0'>"
        f"<p style='margin:0;color:#333'>{message}</p>"
        f"{action_html}"
        "</div>"
    )
