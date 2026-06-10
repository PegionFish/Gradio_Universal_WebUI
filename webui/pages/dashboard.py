# webui/pages/dashboard.py — 仪表盘页面（首页）

import gradio as gr


def create_page(app_state: gr.State) -> gr.HTML:
    """创建仪表盘标签页。"""
    dashboard_html = gr.HTML("加载中...")

    def on_select(state):
        """标签页被选中或 app_state 刷新时从 app_state 读取数据渲染。"""
        services = state.get("services", [])
        tasks = state.get("tasks", [])
        gpu = state.get("gpu_metrics", {"available": False, "snapshots": [], "updated_at": ""})

        running = sum(1 for s in services if s.get("runtime_state") == "running")
        total = len(services)

        parts = [
            "<div style='padding:8px'>",
            f"<p style='font-size:16px'><b>{running}/{total}</b> 个服务运行中 | "
            f"刷新于 {state.get('last_refresh', '')}</p>",
        ]

        # 服务状态
        parts.append("<h4>服务状态</h4><ul>")
        icon_map = {
            "running": "🟢", "unhealthy": "🟡", "starting": "🔵",
            "stopped": "⚪", "exited": "🔴", "stopping": "🔵",
        }
        for s in services:
            icon = icon_map.get(s.get("runtime_state", ""), "⚪")
            parts.append(
                f"<li>{icon} {s.get('display_name', '?')} — "
                f"{s.get('runtime_state', 'unknown')}</li>"
            )
        if not services:
            parts.append("<li>暂无服务配置</li>")
        parts.append("</ul>")

        # 最近任务
        parts.append("<h4>最近任务</h4>")
        if tasks:
            parts.append(
                "<table style='border-collapse:collapse;width:100%;"
                "border:1px solid rgba(128,128,128,0.15)'>"
                "<tr style='background:rgba(128,128,128,0.06)'>"
                "<th style='padding:6px 8px'>ID</th>"
                "<th style='padding:6px 8px'>服务</th>"
                "<th style='padding:6px 8px'>状态</th>"
                "<th style='padding:6px 8px'>时间</th></tr>"
            )
            for t in tasks:
                parts.append(
                    f"<tr>"
                    f"<td style='padding:4px 8px'>{t['id'][:8]}...</td>"
                    f"<td style='padding:4px 8px'>{t.get('service_id', '')}</td>"
                    f"<td style='padding:4px 8px'>{t.get('status', '')}</td>"
                    f"<td style='padding:4px 8px'>{t.get('created_at', '')[:19]}</td>"
                    f"</tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p>暂无任务</p>")

        # GPU 概览
        parts.append("<h4>GPU 概览</h4>")
        if gpu.get("available"):
            for s in gpu.get("snapshots", []):
                mem_total = max(s.get("memory_total_mb", 1), 1)
                mem_pct = int(s.get("memory_used_mb", 0) / mem_total * 100)
                parts.append(
                    f"<p>GPU {s['gpu_index']}: {s.get('name', '')} — "
                    f"{s.get('memory_used_mb', 0)}/{s.get('memory_total_mb', 0)} MiB "
                    f"({mem_pct}%) — {s.get('utilization_percent', 0)}% — "
                    f"{s.get('temperature_celsius', 0)}°C</p>"
                )
        else:
            parts.append(
                "<p style='opacity:0.7'>未检测到 NVIDIA GPU。GPU 监控功能不可用。</p>"
            )

        parts.append("</div>")
        return gr.update(value="".join(parts))

    # 全局状态变更时自动刷新（由顶层 gr.Timer 驱动，每 5 秒触发）
    app_state.change(fn=on_select, inputs=app_state, outputs=dashboard_html)

    # 初始渲染 — 使用空状态避免空白
    dashboard_html.value = on_select({
        "services": [], "tasks": [],
        "gpu_metrics": {"available": False, "snapshots": [], "updated_at": ""},
        "last_refresh": "",
    })["value"]

    return dashboard_html
