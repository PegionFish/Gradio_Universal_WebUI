# webui/pages/gpu.py — GPU 监控页面

import gradio as gr
from core import gpu_monitor


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 GPU 监控标签页。"""
    gr.Markdown("## GPU 监控")

    gpu_dashboard = gr.HTML("加载中...")

    gr.Markdown("---")
    gr.Markdown("### GPU 推荐")
    gr.Markdown("以下按可用显存从高到低排序，适用于新的任务分配。")

    recommendation = gr.HTML("加载中...")
    min_mem_input = gr.Slider(
        minimum=0, maximum=48, value=8, step=1,
        label="最低显存需求 (GB)",
    )

    def refresh_dashboard(state, min_mem_gb):
        gpu = state.get("gpu_metrics", {
            "available": False, "snapshots": [], "updated_at": "",
        })

        if not gpu.get("available"):
            gpu_html_val = (
                "<div style='padding:20px;text-align:center;color:#888'>"
                "<h3>未检测到 NVIDIA GPU</h3>"
                "<p>GPU 监控功能不可用。</p></div>"
            )
            rec_html_val = "<p>GPU 监控不可用。</p>"
        else:
            # GPU 卡片
            cards = []
            for s in gpu.get("snapshots", []):
                mem_total = max(s.get("memory_total_mb", 1), 1)
                mem_pct = int(s.get("memory_used_mb", 0) / mem_total * 100)
                cards.append(
                    f"<div style='border:1px solid #ddd;border-radius:8px;"
                    f"padding:12px;margin:8px;background:#f9f9f9;"
                    f"width:30%;min-width:280px;display:inline-block;"
                    f"vertical-align:top;'>"
                    f"<h4>GPU {s['gpu_index']}: {s.get('name', '')}</h4>"
                    f"<table style='width:100%'>"
                    f"<tr><td>显存</td><td>{s.get('memory_used_mb', 0)}/"
                    f"{s.get('memory_total_mb', 0)} MiB ({mem_pct}%)</td></tr>"
                    f"<tr><td>GPU 利用率</td><td>"
                    f"{s.get('utilization_percent', 0)}%</td></tr>"
                    f"<tr><td>温度</td><td>"
                    f"{s.get('temperature_celsius', 0)}°C</td></tr>"
                    f"<tr><td>功耗</td><td>"
                    f"{s.get('power_milliwatts', 0) / 1000:.1f} W</td></tr>"
                    f"<tr><td>进程</td><td>"
                    f"{len(s.get('processes', []))} 个</td></tr>"
                    f"</table></div>"
                )
            gpu_html_val = (
                "".join(cards)
                + f"<p style='color:#888'>更新于 {gpu.get('updated_at', '')[:19]}</p>"
            )

            # 推荐
            min_mib = int(min_mem_gb) * 1024
            sorted_gpus = sorted(
                [
                    s for s in gpu.get("snapshots", [])
                    if s.get("memory_free_mb", 0) >= min_mib
                ],
                key=lambda s: (
                    -s.get("memory_free_mb", 0),
                    s.get("utilization_percent", 0),
                    s.get("temperature_celsius", 0),
                ),
            )
            if sorted_gpus:
                items = []
                for idx, s in enumerate(sorted_gpus):
                    tag = "🟢 推荐" if idx == 0 else f"{idx+1}."
                    items.append(
                        f"<li>{tag} GPU {s['gpu_index']} — "
                        f"空闲 {s.get('memory_free_mb', 0)} MiB, "
                        f"利用率 {s.get('utilization_percent', 0)}%</li>"
                    )
                rec_html_val = "<ol>" + "".join(items) + "</ol>"
            else:
                rec_html_val = "<p>没有满足最低显存要求的 GPU。</p>"

        return gr.update(value=gpu_html_val), gr.update(value=rec_html_val)

    gpu_dashboard.select(
        refresh_dashboard,
        inputs=[app_state, min_mem_input],
        outputs=[gpu_dashboard, recommendation],
    )

    min_mem_input.change(
        refresh_dashboard,
        inputs=[app_state, min_mem_input],
        outputs=[gpu_dashboard, recommendation],
    )

    return gpu_dashboard
