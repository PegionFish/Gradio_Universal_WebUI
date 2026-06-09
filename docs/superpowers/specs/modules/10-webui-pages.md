# 模块 10：WebUI 页面

## 用途

实现所有 Gradio 标签页的布局、交互回调和组件。每个页面文件独立负责一个标签页的 UI 逻辑。

## 依赖

- **模块 9**：WebUI 主程序组装（顶层 `gr.State`、`gr.Timer`、刷新机制）
- **所有核心模块**：ConfigService、ServiceRegistry、ProcessManager、TaskScheduler、GpuMonitor、ResultManager
- Python 包：`gradio>=5.0`

## 页面通用约定

每个页面文件导出的 `create_page(app_state)` 函数遵循统一约定：

```python
# 所有 pages/*.py 的共同签名:
def create_page(app_state: gr.State) -> gr.HTML:
    """创建标签页。
    
    app_state: 顶层的 gr.State，由 app.py 中的全局 Timer 每 5 秒刷新。
               包含 services / tasks / gpu_metrics 三个数据源的最新快照。
    
    返回: 主输出组件（gr.HTML），供 app.py 的 .select() 事件刷新。
    """
```

### 状态保持原则

1. **数据来自 app_state**：每个页面的动态数据通过顶层 `gr.State` 获取，不在页面内创建独立的数据获取逻辑。
2. **表单状态由 Gradio 自动保持**：文本框、下拉框、滑块等输入组件的值在标签页切换后保持不变（Gradio 使用 CSS `display:none` 隐藏非活跃标签页的 DOM，不会卸载）。
3. **主动刷新**：每个页面提供手动刷新按钮，用户也可以切换到其他标签页再切回来（触发 `.select()` 事件）刷新。
4. **后台服务不依赖 UI**：HealthChecker 和 GpuMonitor 是守护线程，即使所有标签页都未激活也能正常工作。

---

## 10.1 仪表盘 (dashboard.py)

```python
# webui/pages/dashboard.py
import gradio as gr


def create_page(app_state: gr.State) -> gr.HTML:
    dashboard_html = gr.HTML("加载中...")
    
    def on_select(state):
        """标签页被选中时从 app_state 读取数据渲染。"""
        services = state["services"]
        tasks = state["tasks"]
        gpu = state["gpu_metrics"]
        
        running = sum(1 for s in services if s["runtime_state"] == "running")
        total = len(services)
        
        parts = [f"<p><b>{running}/{total}</b> 个服务正在运行</p>"]
        
        parts.append("<h4>服务状态</h4><ul>")
        for s in services:
            icon = {"running": "🟢", "unhealthy": "🟡", "starting": "🔵",
                    "stopped": "⚪", "exited": "🔴"}.get(s["runtime_state"], "⚪")
            parts.append(f"<li>{icon} {s['display_name']} — {s['runtime_state']}</li>")
        parts.append("</ul>")
        
        parts.append("<h4>最近任务</h4>")
        if tasks:
            parts.append("<table border='1' cellpadding='4' style='border-collapse:collapse'>"
                         "<tr><th>ID</th><th>服务</th><th>状态</th><th>时间</th></tr>")
            for t in tasks:
                parts.append(f"<tr><td>{t['id'][:8]}...</td><td>{t['service_id']}</td>"
                             f"<td>{t['status']}</td><td>{t['created_at']}</td></tr>")
            parts.append("</table>")
        else:
            parts.append("<p>暂无任务</p>")
        
        parts.append("<h4>GPU 概览</h4>")
        if gpu["available"]:
            for s in gpu["snapshots"]:
                mem_pct = int(s["memory_used_mb"] / max(s["memory_total_mb"], 1) * 100)
                parts.append(
                    f"<p>GPU {s['gpu_index']}: {s['name']} — "
                    f"{s['memory_used_mb']}/{s['memory_total_mb']} MiB ({mem_pct}%) — "
                    f"{s['utilization_percent']}% — {s['temperature_celsius']}°C</p>"
                )
        else:
            parts.append("<p>未检测到 NVIDIA GPU。</p>")
        
        parts.append(f"<p style='color:#888;font-size:12px'>刷新于 {state['last_refresh']}</p>")
        return gr.update(value="".join(parts))
    
    # 标签页选中时刷新
    dashboard_html.select(on_select, inputs=app_state, outputs=dashboard_html)
    
    return dashboard_html
```

---

## 10.2 服务管理 (services.py)

```python
# webui/pages/services.py
import gradio as gr
from core import registry, process_manager, scheduler


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## 服务管理")
    
    # ── 服务状态表（由顶层刷新）──
    service_table = gr.HTML("加载中...")
    
    gr.Markdown("---")
    gr.Markdown("### 服务控制")
    
    # ── 控制区域 ──
    with gr.Row():
        service_selector = gr.Dropdown(
            label="选择服务",
            choices=[],  # 页面加载时填充
            interactive=True,
            scale=2,
        )
        btn_start = gr.Button("启动", variant="primary", scale=1, min_width=80)
        btn_stop = gr.Button("停止", variant="stop", scale=1, min_width=80)
        btn_restart = gr.Button("重启", variant="secondary", scale=1, min_width=80)
    
    # ── 停止确认对话框（默认隐藏）──
    confirm_stop_html = gr.HTML(visible=False)
    with gr.Row():
        btn_confirm_stop = gr.Button("确认停止", variant="stop", visible=False, scale=1)
        btn_cancel_stop = gr.Button("取消", variant="secondary", visible=False, scale=1)
    
    # ── 操作结果 ──
    status_msg = gr.Textbox(label="操作结果", interactive=False)
    
    # ── 日志查看 ──
    gr.Markdown("---")
    gr.Markdown("### 服务日志")
    log_viewer = gr.Textbox(label="日志 (最后 50 行)", lines=10, interactive=False)
    
    # ── 从 app_state 刷新服务表 ──
    def refresh_from_state(state):
        svc_list = state["services"]
        html = _build_service_table(svc_list)
        choices = [(s["display_name"], s["id"]) for s in svc_list]
        return gr.update(value=html), gr.update(choices=choices)
    
    service_table.select(
        refresh_from_state,
        inputs=app_state,
        outputs=[service_table, service_selector],
    )
    
    # ── 按钮回调 ──
    btn_start.click(
        fn=lambda sid: _on_service_action(sid, "start"),
        inputs=service_selector,
        outputs=status_msg,
    )
    
    btn_stop.click(
        fn=_on_stop_click,
        inputs=service_selector,
        outputs=[confirm_stop_html, status_msg, btn_confirm_stop, btn_cancel_stop],
    )
    
    btn_confirm_stop.click(
        fn=lambda sid: _on_service_action(sid, "stop"),
        inputs=service_selector,
        outputs=status_msg,
    ).then(
        fn=lambda: (gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)),
        outputs=[confirm_stop_html, btn_confirm_stop, btn_cancel_stop],
    )
    
    btn_cancel_stop.click(
        fn=lambda: (gr.update(visible=False), "", gr.update(visible=False), gr.update(visible=False)),
        outputs=[confirm_stop_html, status_msg, btn_confirm_stop, btn_cancel_stop],
    )
    
    btn_restart.click(
        fn=lambda sid: _on_service_action(sid, "restart"),
        inputs=service_selector,
        outputs=status_msg,
    )
    
    # ── 查看日志（选择服务时自动加载）──
    service_selector.change(
        fn=_on_select_service,
        inputs=service_selector,
        outputs=log_viewer,
    )
    
    return service_table


def _build_service_table(svc_list):
    lines = ["<table border='1' cellpadding='6' style='border-collapse:collapse; width:100%'>",
             "<tr><th>ID</th><th>名称</th><th>类型</th><th>状态</th><th>GPU</th><th>URL</th></tr>"]
    for s in svc_list:
        status_display = {
            "running": "🟢 运行中", "stopped": "⚪ 已停止",
            "starting": "🔵 启动中", "unhealthy": "🟡 不健康",
            "stopping": "🔵 停止中", "exited": "🔴 已退出",
        }.get(s["runtime_state"], s["runtime_state"])
        gpu_str = ",".join(map(str, s["gpu_assignment"])) if s["gpu_assignment"] else "不限"
        url_str = s["service_url"] or "(未配置)"
        lines.append(f"<tr><td>{s['id']}</td><td>{s['display_name']}</td>"
                     f"<td>{s['model_type']}</td><td>{status_display}</td>"
                     f"<td>{gpu_str}</td><td>{url_str}</td></tr>")
    lines.append("</table>")
    return "".join(lines)


def _on_service_action(service_id: str, action: str):
    if not service_id:
        return "请先选择一个服务"
    getattr(process_manager, action)(service_id)
    return f"已提交 {action} 请求: {service_id}"


def _on_stop_click(service_id: str):
    if not service_id:
        return [gr.update(visible=False), "请先选择一个服务",
                gr.update(visible=False), gr.update(visible=False)]
    
    running = scheduler.get_running_tasks(service_id)
    if running:
        return [
            gr.update(value=f"<div style='color:orange'>⚠️ 服务 {service_id} 有 "
                     f"{len(running)} 个运行中的任务。停止将中断这些任务。</div>",
                     visible=True),
            "",
            gr.update(visible=True),
            gr.update(visible=True),
        ]
    else:
        _on_service_action(service_id, "stop")
        return [gr.update(visible=False), f"已提交停止请求: {service_id}",
                gr.update(visible=False), gr.update(visible=False)]


def _on_select_service(service_id: str):
    if not service_id:
        return "(选择服务后查看日志)"
    log = process_manager.tail_log(service_id)
    return log
```

> **注意**：`process_manager.tail_log()` 需要在 ProcessManager 中补充实现，读取 `data/logs/services/<id>/<timestamp>.log` 最后 50 行。

---

## 10.3 任务管理 (tasks.py)

```python
# webui/pages/tasks.py
import gradio as gr
from core import registry, scheduler, result_mgr


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## 任务管理")
    
    # ── 筛选区 ──
    with gr.Row():
        filter_service = gr.Dropdown(
            label="筛选服务",
            choices=[],
            interactive=True,
            scale=1,
        )
        filter_status = gr.Dropdown(
            label="筛选状态",
            choices=["全部", "queued", "running", "completed", "failed", "cancelled"],
            value="全部",
            interactive=True,
            scale=1,
        )
        btn_refresh = gr.Button("刷新", variant="secondary", scale=0)
    
    # ── 任务列表 ──
    task_list = gr.HTML("加载中...")
    
    # ── 任务详情 ──
    gr.Markdown("---")
    gr.Markdown("### 任务详情")
    with gr.Row():
        task_id_input = gr.Textbox(label="任务 ID", placeholder="输入任务 ID 查看详情", scale=3)
        btn_view = gr.Button("查看", variant="secondary", scale=1)
    
    with gr.Row():
        task_detail = gr.JSON(label="任务数据")
        result_files = gr.HTML(label="输出文件")
    
    # ── 从 app_state 刷新 ──
    def refresh_from_state(state):
        svc_list = state["services"]
        svc_choices = [("全部服务", "")] + [(s["display_name"], s["id"]) for s in svc_list]
        return gr.update(choices=svc_choices)
    
    task_list.select(
        refresh_from_state,
        inputs=app_state,
        outputs=filter_service,
    )
    
    def load_tasks(svc_filter, status_filter):
        status = status_filter if status_filter != "全部" else None
        sid = svc_filter if svc_filter else None
        tasks = scheduler.list_tasks(service_id=sid, status=status)
        
        if not tasks:
            return gr.update(value="<p>暂无任务</p>")
        
        lines = ["<table border='1' cellpadding='4' style='border-collapse:collapse; width:100%'>",
                 "<tr><th>ID</th><th>服务</th><th>模型</th><th>状态</th><th>创建时间</th><th>错误</th></tr>"]
        for t in tasks:
            error = t.get("error_summary", "") or ""
            lines.append(f"<tr><td>{t['id'][:8]}...</td><td>{t['service_id']}</td>"
                         f"<td>{t['model_type']}</td><td>{t['status']}</td>"
                         f"<td>{t['created_at'][:19]}</td>"
                         f"<td style='color:red'>{error[:40]}...</td></tr>")
        lines.append("</table>")
        return gr.update(value="".join(lines))
    
    btn_refresh.click(
        load_tasks,
        inputs=[filter_service, filter_status],
        outputs=task_list,
    )
    
    filter_status.change(load_tasks, inputs=[filter_service, filter_status], outputs=task_list)
    filter_service.change(load_tasks, inputs=[filter_service, filter_status], outputs=task_list)
    
    def view_task(task_id):
        if not task_id:
            return {}, ""
        task = scheduler.get_task(task_id)
        if not task:
            return {"error": "任务不存在"}, ""
        files = result_mgr.list_outputs(task_id)
        files_html = "<ul>" + "".join(f"<li>{f}</li>" for f in files) + "</ul>" if files else "<p>(无输出文件)</p>"
        return task, files_html
    
    btn_view.click(view_task, inputs=task_id_input, outputs=[task_detail, result_files])
    
    return task_list
```

---

## 10.4 GPU 监控 (gpu.py)

```python
# webui/pages/gpu.py
import gradio as gr
from core import gpu_monitor


def create_page(app_state: gr.State) -> gr.HTML:
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
        gpu = state["gpu_metrics"]
        
        # GPU 卡片
        if not gpu["available"]:
            gpu_html_val = "<div style='padding:20px;text-align:center;color:#888'><h3>未检测到 NVIDIA GPU</h3></div>"
            rec_html_val = "<p>GPU 监控不可用。</p>"
        else:
            cards = []
            for s in gpu["snapshots"]:
                mem_pct = int(s["memory_used_mb"] / max(s["memory_total_mb"], 1) * 100)
                cards.append(
                    f"<div style='border:1px solid #ddd;border-radius:8px;padding:12px;margin:8px;"
                    f"background:#f9f9f9;width:30%;min-width:280px;display:inline-block;vertical-align:top;'>"
                    f"<h4>GPU {s['gpu_index']}: {s['name']}</h4>"
                    f"<table style='width:100%'>"
                    f"<tr><td>显存</td><td>{s['memory_used_mb']}/{s['memory_total_mb']} MiB ({mem_pct}%)</td></tr>"
                    f"<tr><td>GPU 利用率</td><td>{s['utilization_percent']}%</td></tr>"
                    f"<tr><td>温度</td><td>{s['temperature_celsius']}°C</td></tr>"
                    f"<tr><td>功耗</td><td>{s['power_milliwatts'] / 1000:.1f} W</td></tr>"
                    f"<tr><td>进程</td><td>{len(s['processes'])} 个</td></tr>"
                    f"</table></div>"
                )
            gpu_html_val = "".join(cards) + f"<p style='color:#888'>更新于 {gpu['updated_at'][:19]}</p>"
            
            # 推荐
            min_mib = int(min_mem_gb) * 1024
            sorted_gpus = sorted(
                [s for s in gpu["snapshots"] if s["memory_free_mb"] >= min_mib],
                key=lambda s: (-s["memory_free_mb"], s["utilization_percent"], s["temperature_celsius"])
            )
            if sorted_gpus:
                items = []
                for idx, s in enumerate(sorted_gpus):
                    tag = "🟢 推荐" if idx == 0 else f"{idx+1}."
                    items.append(f"<li>{tag} GPU {s['gpu_index']} — "
                                f"空闲 {s['memory_free_mb']} MiB, 利用率 {s['utilization_percent']}%</li>")
                rec_html_val = "<ol>" + "".join(items) + "</ol>"
            else:
                rec_html_val = "<p>没有满足最低显存要求的 GPU。</p>"
        
        return gr.update(value=gpu_html_val), gr.update(value=rec_html_val)
    
    # 标签页选中时渲染 + 滑块变更时重新计算推荐
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
```

---

## 10.5 配置 (config.py)

```python
# webui/pages/config.py
import gradio as gr
import yaml
from core import config as cfg
from core.config_service import ConfigError


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## 配置管理")
    
    gr.Markdown("""
    编辑 `config/services.yaml` 的完整内容。
    修改后点击保存，系统将校验并持久化。
    """)
    
    yaml_editor = gr.Textbox(
        label="services.yaml",
        lines=25,
        max_lines=40,
        value="",
        interactive=True,
    )
    
    with gr.Row():
        btn_load = gr.Button("重新加载", variant="secondary")
        btn_save = gr.Button("保存", variant="primary")
    
    save_status = gr.Textbox(label="状态", interactive=False)
    error_display = gr.Textbox(label="校验错误", lines=5, interactive=False)
    
    # 加载当前配置
    def load_yaml():
        services = cfg.get_services_list()
        payload = {"services": services}
        yaml_text = yaml.dump(payload, default_flow_style=False, allow_unicode=True)
        return yaml_text, "", ""
    
    btn_load.click(load_yaml, outputs=[yaml_editor, save_status, error_display])
    
    # 保存
    def save_yaml(yaml_text: str):
        try:
            parsed = yaml.safe_load(yaml_text)
            if not isinstance(parsed, dict):
                raise ConfigError("YAML 必须是一个字典")
            services_list = parsed.get("services", [])
            cfg.save_services_config(services_list)
            from core import registry
            registry.load_from_config(services_list)
            return "保存成功", ""
        except yaml.YAMLError as e:
            return "", f"YAML 解析错误: {e}"
        except ConfigError as e:
            return "", f"配置校验错误: {e}"
    
    btn_save.click(save_yaml, inputs=yaml_editor, outputs=[save_status, error_display])
    
    return gr.HTML("")  # 配置页不使用 app_state 刷新
```

---

## 10.6 模型入口页面（占位）

所有四个模型入口页面结构相同，仅标题和模型类型不同。这里以 Stable Diffusion 为例。

```python
# webui/pages/stable_diffusion.py
import gradio as gr
from adapters import get_adapter
from core import registry, scheduler, result_mgr, gpu_monitor


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## Stable Diffusion")
    
    # 检查适配器
    try:
        adapter = get_adapter("stable-diffusion")
    except ValueError:
        gr.Markdown("> **适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")
    
    # ── 占位提示 ──
    gr.Markdown(
        "> **Stable Diffusion 适配器当前为占位状态。** "
        "配置并启动服务后，在此页面提交推理任务。"
        "当前提交的任务会记录到任务管理，但不会实际执行推理。"
    )
    
    # ── 服务选择（动态从 registry 读取）──
    svc_list = registry.get_by_model_type("stable-diffusion")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    
    service_selector = gr.Dropdown(
        label="服务",
        choices=service_choices,
        interactive=True,
        scale=2,
    )
    
    # ── GPU 选择（从 gpu_monitor 动态拉取）──
    metrics = gpu_monitor.get_latest()
    if metrics.available:
        recommended = gpu_monitor.recommend()
        gpu_choices = [(f"GPU {s.gpu_index} — 空闲 {s.memory_free_mb} MiB", str(s.gpu_index))
                       for s in metrics.snapshots]
        default_gpu = str(recommended[0]) if recommended else ""
    else:
        gpu_choices = [("自动", "")]
        default_gpu = ""
    
    gpu_selector = gr.Dropdown(
        label="目标 GPU",
        choices=gpu_choices,
        value=default_gpu,
        interactive=True,
        scale=1,
    )
    
    # ── 模型参数（输入组件的值在切换标签页后自动保持）──
    prompt = gr.Textbox(label="提示词 (Prompt)", lines=3, placeholder="输入提示词...")
    with gr.Row():
        width = gr.Slider(256, 2048, value=512, step=64, label="宽度")
        height = gr.Slider(256, 2048, value=512, step=64, label="高度")
    with gr.Row():
        steps = gr.Slider(1, 150, value=20, step=1, label="采样步数")
        cfg_scale = gr.Slider(1.0, 30.0, value=7.0, step=0.5, label="CFG 缩放")
    
    btn_submit = gr.Button("提交任务", variant="primary")
    
    # ── 结果展示 ──
    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.Textbox(label="状态", interactive=False)
    error_output = gr.Textbox(label="错误信息", lines=3, interactive=False)
    
    # ── 提交回调 ──
    def on_submit(service_id, gpu_idx, prompt_text, w, h, st, cfg):
        if not service_id:
            return "", "错误", "请先选择服务"
        
        task_id = scheduler.create_task(
            service_id=service_id,
            model_type="stable-diffusion",
            adapter_name="StableDiffusionAdapter",
            request_payload={
                "prompt": prompt_text,
                "width": w, "height": h,
                "steps": st, "cfg_scale": cfg,
            },
            target_gpu=[int(gpu_idx)] if gpu_idx else None,
        )
        
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {
            "prompt": prompt_text, "width": w, "height": h, "steps": st,
        })
        
        try:
            adapter = get_adapter("stable-diffusion")
            service_url = registry.get(service_id).service_url
            adapter.submit(service_url, {"prompt": prompt_text},
                          target_gpu=[int(gpu_idx)] if gpu_idx else None)
            return task_id, "完成", ""
        except NotImplementedError as e:
            scheduler.update_task_status(task_id, "failed", error_summary=str(e))
            result_mgr.save_log(task_id, "error.log", str(e))
            return task_id, "失败", str(e)
        except Exception as e:
            scheduler.update_task_status(task_id, "failed", error_summary=f"提交失败: {e}")
            return task_id, "错误", str(e)
    
    btn_submit.click(
        fn=on_submit,
        inputs=[service_selector, gpu_selector, prompt, width, height, steps, cfg_scale],
        outputs=[task_id_output, status_output, error_output],
    )
    
    return gr.HTML("")
```

### Qwen3ASR / WhisperX / FastWhisper 入口页

结构同上，仅替换：

| 字段 | stable_diffusion.py | qwen3_asr.py | whisperx.py | fastwhisper.py |
|------|-------------------|-------------|-------------|---------------|
| 标题 | Stable Diffusion | Qwen3 ASR | WhisperX | FastWhisper |
| model_type | `stable-diffusion` | `qwen3-asr` | `whisperx` | `fastwhisper` |
| adapter_name | StableDiffusionAdapter | Qwen3ASRAdapter | WhisperXAdapter | FastWhisperAdapter |
| 预留参数 | prompt, width/height, steps, cfg_scale | 音频文件上传、语言选择 | 音频文件上传 | 音频文件上传 |

Qwen3ASR 入口页的预留参数区参考 `E:\Qwen3ASR\qwen-asr-1.7B\app.py`：

```python
# qwen3_asr.py 预留参数（第二阶段实现）:
# - audio_input: gr.Audio(label="音频输入", type="numpy")
# - language: gr.Dropdown(label="语种", choices=["Auto", "zh", "en"])
# - return_timestamps: gr.Checkbox(label="返回时间戳")
# - transcribe_btn: gr.Button("转录")
# - result_text: gr.Textbox(label="识别结果")
# - srt_output: gr.Textbox(label="SRT 字幕")
```

---

## 后台服务与 UI 无关性保证

为确保多标签页场景下所有服务持续运行，需遵循以下设计原则：

### 1. 所有核心服务是守护线程

```python
# core/health_checker.py 启动方式
thread = threading.Thread(target=self._run_loop, daemon=True)

# core/gpu_monitor.py 启动方式
thread = threading.Thread(target=self._refresh_loop, daemon=True)
```

`daemon=True` 的线程在 WebUI 进程存活期间持续运行，不受浏览器是否打开、当前在哪个标签页影响。

### 2. UI 只读不写后台数据

```python
# ✅ 正确：UI 只读取数据
gpu = gpu_monitor.get_latest()
services = registry.list_services()

# ❌ 错误：UI 不应直接管理后台线程生命周期
# gpu_monitor._thread.join()  # 不要这样做
```

### 3. 表单状态不依赖后台

用户在当前标签页填写的表单值（如 prompt、steps、width）存储在 Gradio 的 DOM 中（`display:none` 保留），切换标签页再切回来时值不变。即使后台重启也不影响已渲染的表单。

### 4. 任务提交不依赖 UI 线程

```python
# 当用户点击"提交"按钮时:
# 1. TaskScheduler.create_task() → 写入 SQLite（持久化）
# 2. 适配器提交（即使异步提交失败，任务记录已在 SQLite 中）
# 3. 用户切换到任务管理标签页可查看状态
# 4. 即使 WebUI 重启，SQLite 中的任务记录不丢失
```

---

## 组件目录

### components/ 结构

第一阶段中，所有 UI 组件逻辑保留在各页面文件中（`_build_*` 辅助函数）。第二阶段若出现跨页面复用的 UI 模式，再抽取到 `components/`：

```python
# webui/components/  — 第二阶段
# ├── service_table.py        # 服务状态表组件
# ├── task_list.py            # 任务列表组件
# ├── gpu_dashboard.py        # GPU 仪表盘组件
# ├── config_editor.py        # 配置编辑器组件
# └── error_display.py        # 错误展示组件
```

---

## 验收标准

1. **仪表盘** — 切换到标签页时显示最新的服务摘要和 GPU 概览
2. **服务管理** — 显示服务表、选择后可启动/停止/重启、查看日志
3. **服务管理** — 停止有运行中任务的服务时弹出确认对话框
4. **服务管理** — 启动/停止操作由后台工作线程执行，不阻塞 UI
5. **任务管理** — 按服务和状态筛选任务、查看详情和输出文件
6. **GPU 监控** — 每 5 秒刷新的 GPU 指标卡片、按显存需求的推荐排序
7. **GPU 监控** — 无 NVIDIA GPU 时显示降级提示
8. **配置** — 加载/编辑/保存 services.yaml，校验失败不覆盖文件
9. **模型入口页** — 占位状态显示适配器未实现提示
10. **模型入口页** — 提交任务后写入 SQLite，可在任务管理查看失败记录
11. **状态保持** — 在模型入口页填写表单，切换到其他标签页再切回来，输入值不变
12. **状态保持** — 后台线程在浏览器切换标签页时持续运行
13. **状态保持** — 从标签页 A 切换到 B 时，B 显示最新的后台数据
