# webui/components/gpu_dashboard.py — GPU 监控仪表盘组件

import gradio as gr


def build_gpu_cards_html(gpu_metrics: dict) -> str:
    """从 GPU 指标字典构建 GPU 卡片 HTML。

    Args:
        gpu_metrics: {"available": bool, "snapshots": [...], "updated_at": "..."}

    Returns:
        HTML 卡片字符串；NVML 不可用时返回降级提示。
    """
    if not gpu_metrics.get("available"):
        return (
            "<div style='padding:40px;text-align:center;color:#888'>"
            "<p style='font-size:48px'>🎮</p>"
            "<h3>未检测到 NVIDIA GPU</h3>"
            "<p>GPU 监控功能不可用。请确认 NVIDIA 驱动和 NVML 库已安装。</p>"
            "</div>"
        )

    snapshots = gpu_metrics.get("snapshots", [])
    if not snapshots:
        return (
            "<div style='text-align:center;padding:20px;color:#888'>"
            "<p>无 GPU 数据。正在采集...</p></div>"
        )

    cards = []
    for s in snapshots:
        mem_total = max(s.get("memory_total_mb", 1), 1)
        mem_pct = int(s.get("memory_used_mb", 0) / mem_total * 100)
        mem_bar_color = (
            "#4caf50" if mem_pct < 50 else "#f0a500" if mem_pct < 80 else "#e74c3c"
        )

        # 利用率颜色
        util = s.get("utilization_percent", 0)
        util_color = "#4caf50" if util < 50 else "#f0a500" if util < 80 else "#e74c3c"

        # 温度颜色
        temp = s.get("temperature_celsius", 0)
        temp_color = "#4caf50" if temp < 65 else "#f0a500" if temp < 85 else "#e74c3c"

        cards.append(
            f"""<div style="border:1px solid #e0e0e0;border-radius:12px;
padding:16px;margin:8px;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,0.08);
width:calc(33% - 24px);min-width:300px;display:inline-block;vertical-align:top;">
<h4 style="margin:0 0 12px 0;font-size:16px">
  GPU {s.get('gpu_index', '?')}: {s.get('name', 'Unknown')}
</h4>
<table style="width:100%;font-size:13px">
<tr><td style="padding:4px 0">显存</td>
  <td style="text-align:right">{s.get('memory_used_mb', 0)} / {s.get('memory_total_mb', 0)} MiB
  <div style="background:#eee;height:6px;border-radius:3px;margin-top:2px">
    <div style="background:{mem_bar_color};height:6px;border-radius:3px;
      width:{mem_pct}%"></div></div>
  </td></tr>
<tr><td style="padding:4px 0">GPU 利用率</td>
  <td style="text-align:right;color:{util_color};font-weight:600">{util}%</td></tr>
<tr><td style="padding:4px 0">温度</td>
  <td style="text-align:right;color:{temp_color};font-weight:600">{temp}°C</td></tr>
<tr><td style="padding:4px 0">功耗</td>
  <td style="text-align:right">{s.get('power_milliwatts', 0) / 1000:.1f} W</td></tr>
<tr><td style="padding:4px 0">活跃进程</td>
  <td style="text-align:right">{len(s.get('processes', []))} 个</td></tr>
</table></div>"""
        )

    updated = gpu_metrics.get("updated_at", "")[:19]
    return (
        "".join(cards)
        + f"<p style='color:#aaa;font-size:11px;text-align:right;margin-top:8px'>"
        f"更新于 {updated}</p>"
    )


def render_gpu_recommendation():
    """渲染 GPU 推荐控件。

    Returns:
        (min_mem_input, recommendation_html)
    """
    min_mem_input = gr.Slider(
        minimum=0, maximum=48, value=8, step=1,
        label="最低显存需求 (GB)",
    )
    recommendation_html = gr.HTML("加载中...")
    return min_mem_input, recommendation_html


def build_recommendation_html(gpu_metrics: dict, min_memory_gb: int) -> str:
    """构建 GPU 推荐排序 HTML。

    Args:
        gpu_metrics: GPU 指标字典
        min_memory_gb: 最低显存需求（GB）

    Returns:
        有序列表 HTML
    """
    if not gpu_metrics.get("available"):
        return "<p style='color:#888'>GPU 监控不可用。</p>"

    snapshots = gpu_metrics.get("snapshots", [])
    if not snapshots:
        return "<p style='color:#888'>无 GPU 数据。</p>"

    min_mib = min_memory_gb * 1024
    eligible = [s for s in snapshots if s.get("memory_free_mb", 0) >= min_mib]

    if not eligible:
        return (
            f"<p style='color:#e67e22'>⚠️ 没有 GPU 满足最低 {min_memory_gb} GB 显存要求。</p>"
            "<p style='color:#888;font-size:12px'>您可以手动选择不满足要求的 GPU，但可能导致显存溢出。</p>"
        )

    sorted_gpus = sorted(
        eligible,
        key=lambda s: (
            -s.get("memory_free_mb", 0),
            s.get("utilization_percent", 0),
            s.get("temperature_celsius", 0),
        ),
    )

    items = []
    for idx, s in enumerate(sorted_gpus):
        tag = f'<span style="color:#4caf50;font-weight:700">🟢 推荐</span>' if idx == 0 else f"{idx + 1}."
        items.append(
            f"<li style='margin:8px 0'>{tag} "
            f"<b>GPU {s.get('gpu_index', '?')}</b> — "
            f"{s.get('memory_free_mb', 0)} MiB 空闲, "
            f"利用率 {s.get('utilization_percent', 0)}%, "
            f"温度 {s.get('temperature_celsius', 0)}°C</li>"
        )
    return "<ol style='font-size:14px'>" + "".join(items) + "</ol>"
