# webui/pages/dashboard.py — 仪表盘页面（首页）

import gradio as gr


def create_page(app_state: gr.State) -> gr.HTML:
    """创建仪表盘标签页。"""
    dashboard_html = gr.HTML("加载中...")

    def on_select(state):
        """标签页被选中时从 app_state 读取数据渲染。"""
        services = state.get("services", [])
        tasks = state.get("tasks", [])
        gpu = state.get("gpu_metrics", {"available": False, "snapshots": [], "updated_at": ""})

        running = sum(1 for s in services if s.get("runtime_state") == "running")
        total = len(services)

        parts = [
            "<div style='padding:16px'>",
            f"<p style='font-size:18px'><b>{running}/{total}</b> 个服务正在运行 | "
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
                "<table border='1' cellpadding='4' style='border-collapse:collapse'>"
                "<tr><th>ID</th><th>服务</th><th>状态</th><th>时间</th></tr>"
            )
            for t in tasks:
                parts.append(
                    f"<tr><td>{t['id'][:8]}...</td><td>{t.get('service_id', '')}</td>"
                    f"<td>{t.get('status', '')}</td>"
                    f"<td>{t.get('created_at', '')[:19]}</td></tr>"
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
                "<p style='color:#888'>未检测到 NVIDIA GPU。GPU 监控功能不可用。</p>"
            )

        parts.append("</div>")
        return gr.update(value="".join(parts))

    # 标签页选中时刷新
    dashboard_html.select(on_select, inputs=app_state, outputs=dashboard_html)

    return dashboard_html
