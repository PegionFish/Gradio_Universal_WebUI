# webui/pages/gpu.py — GPU 监控页面

import gradio as gr


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
                "<div style='padding:40px;text-align:center;opacity:0.7'>"
                "<p style='font-size:48px'>🎮</p>"
                "<h3>未检测到 NVIDIA GPU</h3>"
                "<p>GPU 监控功能不可用。</p></div>"
            )
            rec_html_val = "<p style='opacity:0.7'>GPU 监控不可用。</p>"
        else:
            # GPU 卡片
            cards = []
            for s in gpu.get("snapshots", []):
                mem_total = max(s.get("memory_total_mb", 1), 1)
                mem_pct = int(s.get("memory_used_mb", 0) / mem_total * 100)
                mem_bar_color = (
                    "#4caf50" if mem_pct < 50 else "#f0a500" if mem_pct < 80 else "#e74c3c"
                )
                util = s.get("utilization_percent", 0)
                util_color = (
                    "#4caf50" if util < 50 else "#f0a500" if util < 80 else "#e74c3c"
                )
                temp = s.get("temperature_celsius", 0)
                temp_color = (
                    "#4caf50" if temp < 65 else "#f0a500" if temp < 85 else "#e74c3c"
                )

                cards.append(
                    f"""<div style="border:1px solid rgba(128,128,128,0.2);
border-radius:12px;padding:16px;margin:8px;
background:rgba(128,128,128,0.04);
box-shadow:0 1px 3px rgba(0,0,0,0.08);
width:calc(33% - 24px);min-width:300px;display:inline-block;vertical-align:top;">
<h4 style="margin:0 0 12px 0;font-size:16px">
  GPU {s.get('gpu_index', '?')}: {s.get('name', 'Unknown')}
</h4>
<table style="width:100%;font-size:13px">
<tr><td style="padding:4px 0">显存</td>
  <td style="text-align:right">{s.get('memory_used_mb', 0)} / {s.get('memory_total_mb', 0)} MiB
  <div style="background:rgba(128,128,128,0.15);height:6px;border-radius:3px;margin-top:2px">
    <div style="background:{mem_bar_color};height:6px;border-radius:3px;
      width:{mem_pct}%"></div></div>
  </td></tr>
<tr><td style="padding:4px 0">GPU 利用率</td>
  <td style="text-align:right;color:{util_color};font-weight:600">{util}%</td></tr>
<tr><td style="padding:4px 0">温度</td>
  <td style="text-align:right;color:{temp_color};font-weight:600">{temp}°C</td></tr>
<tr><td style="padding:4px 0">功耗</td>
  <td style="text-align:right">{s.get('power_milliwatts', 0) / 1000:.1f} W</td></tr>
<tr><td style="padding:4px 0">进程</td>
  <td style="text-align:right">{len(s.get('processes', []))} 个</td></tr>
</table></div>"""
                )
            gpu_html_val = (
                "".join(cards)
                + f"<p style='opacity:0.7;font-size:11px;text-align:right;"
                f"margin-top:8px'>更新于 {gpu.get('updated_at', '')[:19]}</p>"
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
                    tag = (
                        '<span style="color:#4caf50;font-weight:700">🟢 推荐</span>'
                        if idx == 0 else f"{idx + 1}."
                    )
                    items.append(
                        f"<li style='margin:8px 0'>{tag} <b>GPU {s.get('gpu_index', '?')}</b> — "
                        f"空闲 {s.get('memory_free_mb', 0)} MiB, "
                        f"利用率 {s.get('utilization_percent', 0)}%</li>"
                    )
                rec_html_val = (
                    f"<ol style='font-size:14px;padding-left:20px'>"
                    + "".join(items) + "</ol>"
                )
            else:
                rec_html_val = (
                    f"<p style='color:#e67e22'>"
                    f"⚠️ 没有 GPU 满足最低 {min_mem_gb} GB 显存要求。</p>"
                )

        return gr.update(value=gpu_html_val), gr.update(value=rec_html_val)

    # 全局状态变更时自动刷新（由顶层 gr.Timer 驱动，每 5 秒触发）
    app_state.change(
        fn=refresh_dashboard,
        inputs=[app_state, min_mem_input],
        outputs=[gpu_dashboard, recommendation],
    )

    # Slider 变更时立即刷新（用户交互）
    min_mem_input.change(
        fn=refresh_dashboard,
        inputs=[app_state, min_mem_input],
        outputs=[gpu_dashboard, recommendation],
    )

    # 初始渲染 — 使用空状态
    empty_state = {
        "services": [], "tasks": [],
        "gpu_metrics": {"available": False, "snapshots": [], "updated_at": ""},
        "last_refresh": "",
    }
    dash_val, rec_val = refresh_dashboard(empty_state, 8)
    gpu_dashboard.value = dash_val["value"]
    recommendation.value = rec_val["value"]

    return gpu_dashboard
