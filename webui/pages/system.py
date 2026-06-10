# webui/pages/system.py — 系统健康监控页面

import gradio as gr
from core.system_monitor import SystemMonitor
from webui.components.progress_indicator import build_progress_bar

# 全局引用（由 app.py 传入）
_monitor: SystemMonitor | None = None


def set_monitor(monitor: SystemMonitor):
    global _monitor
    _monitor = monitor


def create_page(app_state: gr.State) -> gr.HTML:
    """创建系统健康标签页。"""
    gr.Markdown("## 🖥️ 系统健康")

    gr.Markdown(
        "监控宿主机的 CPU、内存和磁盘使用情况。"
        "当资源使用率达到 85% 时发出警告，95% 时发出严重告警。"
    )

    system_status = gr.HTML("加载中...")
    refresh_btn = gr.Button("🔄 刷新", variant="secondary")

    def refresh():
        if _monitor is None:
            return gr.update(
                value="<p style='color:#888;text-align:center;padding:20px'>"
                "系统监控未初始化。请安装 psutil: pip install psutil</p>"
            )

        metrics = _monitor.get_latest()
        if not metrics.available:
            return gr.update(
                value="<div style='text-align:center;padding:40px;color:#888'>"
                "<p style='font-size:40px'>🖥️</p>"
                "<h3>系统监控不可用</h3>"
                "<p>请安装 psutil: pip install psutil</p></div>"
            )

        alerts = _monitor.check_alerts()
        parts = ["<div style='padding:8px'>"]

        # 告警
        if alerts:
            parts.append("<div style='margin-bottom:16px'>")
            for a in alerts:
                level_color = "#c62828" if a["level"] == "critical" else "#e65100"
                icon = "🔴" if a["level"] == "critical" else "🟡"
                parts.append(
                    f"<div style='border-left:4px solid {level_color};"
                    f"background:#fff;padding:8px 12px;margin:4px 0;"
                    f"border-radius:4px'>{icon} {a['message']}</div>"
                )
            parts.append("</div>")

        # CPU
        if metrics.cpu:
            cpu = metrics.cpu
            cpu_color = (
                "#c62828" if cpu.percent_used > 90
                else "#e65100" if cpu.percent_used > 70
                else "#4caf50"
            )
            parts.append(
                f"<h4>CPU</h4>"
                f"<p>{cpu.core_count} 核心 | "
                f"<span style='color:{cpu_color};font-weight:700'>"
                f"{cpu.percent_used:.1f}%</span></p>"
            )
            parts.append(build_progress_bar(cpu.percent_used, ""))

            if cpu.load_avg_1min > 0:
                parts.append(
                    f"<p style='font-size:12px;color:#888'>"
                    f"Load avg: {cpu.load_avg_1min:.1f} / "
                    f"{cpu.load_avg_5min:.1f} / {cpu.load_avg_15min:.1f}</p>"
                )

        # 内存
        if metrics.memory:
            mem = metrics.memory
            mem_color = (
                "#c62828" if mem.percent_used > 90
                else "#e65100" if mem.percent_used > 70
                else "#4caf50"
            )
            parts.append(
                f"<h4 style='margin-top:16px'>内存</h4>"
                f"<p>已用 {mem.used_gb:.1f} GB / 总计 {mem.total_gb:.1f} GB | "
                f"可用 {mem.available_gb:.1f} GB | "
                f"<span style='color:{mem_color};font-weight:700'>"
                f"{mem.percent_used:.0f}%</span></p>"
            )
            parts.append(build_progress_bar(mem.percent_used, ""))
            if mem.swap_total_gb > 0:
                parts.append(
                    f"<p style='font-size:12px;color:#888'>"
                    f"SWAP: {mem.swap_used_gb:.1f} / {mem.swap_total_gb:.1f} GB</p>"
                )

        # 磁盘
        parts.append("<h4 style='margin-top:16px'>磁盘</h4>")
        for disk in metrics.disks:
            disk_color = (
                "#c62828" if disk.percent_used > 90
                else "#e65100" if disk.percent_used > 70
                else "#4caf50"
            )
            parts.append(
                f"<p><b>{disk.mountpoint}</b> ({disk.device}) — "
                f"{disk.used_gb:.1f} / {disk.total_gb:.1f} GB | "
                f"<span style='color:{disk_color};font-weight:700'>"
                f"{disk.percent_used:.0f}%</span></p>"
            )
            parts.append(build_progress_bar(disk.percent_used, ""))

        parts.append(
            f"<p style='color:#aaa;font-size:11px;text-align:right;margin-top:8px'>"
            f"更新于 {metrics.updated_at[:19]}</p>"
        )
        parts.append("</div>")
        return gr.update(value="".join(parts))

    refresh_btn.click(fn=refresh, outputs=system_status)

    # 初次加载
    system_status.value = refresh()["value"]

    return system_status
