# webui/components/progress_indicator.py — 进度指示器组件

import gradio as gr


def build_progress_bar(progress: float, label: str = "") -> str:
    """构建进度条 HTML。

    Args:
        progress: 0-100 的进度百分比
        label: 可选的标签文本

    Returns:
        HTML 进度条
    """
    progress = max(0, min(100, progress))
    color = (
        "#4caf50" if progress >= 100
        else "#2196f3" if progress >= 50
        else "#ff9800" if progress >= 10
        else "#e0e0e0"
    )

    pct_text = f"{progress:.0f}%"
    return (
        f"<div style='margin:8px 0'>"
        f"{f'<span style=font-size:12px;color:#666>{label}</span>' if label else ''}"
        f"<div style='background:#eee;height:20px;border-radius:10px;overflow:hidden;"
        f"margin-top:4px'>"
        f"<div style='background:{color};height:20px;width:{progress}%;"
        f"border-radius:10px;transition:width 0.3s;display:flex;"
        f"align-items:center;justify-content:center'>"
        f"<span style='color:white;font-size:11px;font-weight:600;"
        f"text-shadow:0 0 2px rgba(0,0,0,0.5)'>{pct_text}</span>"
        f"</div></div></div>"
    )


def build_status_badge(status: str) -> str:
    """构建状态徽章 HTML。

    Args:
        status: 任务状态

    Returns:
        彩色状态徽章 HTML
    """
    colors = {
        "queued": ("#e3f2fd", "#1565c0", "📋 排队中"),
        "running": ("#fff3e0", "#e65100", "🔄 运行中"),
        "completed": ("#e8f5e9", "#2e7d32", "✅ 已完成"),
        "failed": ("#ffebee", "#c62828", "❌ 失败"),
        "cancelled": ("#f5f5f5", "#757575", "🚫 已取消"),
        "retrying": ("#e8eaf6", "#283593", "🔄 重试中"),
    }
    bg, fg, label = colors.get(status, ("#f5f5f5", "#333", status))

    return (
        f"<span style='display:inline-block;background:{bg};color:{fg};"
        f"padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600'>"
        f"{label}</span>"
    )


def build_task_timeline(task: dict) -> str:
    """构建任务时间线 HTML。

    Args:
        task: 任务字典

    Returns:
        HTML 时间线
    """
    events = []

    created = task.get("created_at", "")
    if created:
        events.append(("📋 创建", created[:19]))

    started = task.get("started_at", "")
    if started:
        events.append(("▶️ 开始", started[:19]))

    status = task.get("status", "queued")
    finished = task.get("finished_at", "")
    if finished:
        icon = "✅" if status == "completed" else "❌" if status == "failed" else "🚫"
        events.append((f"{icon} {status}", finished[:19]))

    retry = task.get("retry_count", 0)
    if retry > 0:
        events.append(("🔄 重试", f"第 {retry} 次"))

    if not events:
        return "<p style='color:#888'>无时间线数据</p>"

    parts = ["<div style='position:relative;padding-left:24px'>"]
    for i, (label, time) in enumerate(events):
        is_last = i == len(events) - 1
        dot_color = "#4caf50" if is_last else "#2196f3"
        line = "" if is_last else (
            f"<div style='position:absolute;left:6px;top:16px;"
            f"width:2px;height:24px;background:#ddd'></div>"
        )
        parts.append(
            f"<div style='position:relative;padding:4px 0'>"
            f"<div style='position:absolute;left:-18px;top:8px;"
            f"width:12px;height:12px;border-radius:50%;background:{dot_color}'></div>"
            f"{line}"
            f"<span style='font-weight:600'>{label}</span> "
            f"<span style='color:#888;font-size:12px'>{time}</span>"
            f"</div>"
        )
    parts.append("</div>")
    return "".join(parts)
