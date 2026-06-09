# 模块 10：WebUI 页面

## 用途

实现所有 Gradio 标签页的布局、交互回调和组件。每个页面文件独立负责一个标签页的 UI 逻辑。

## 依赖

- **模块 9**：WebUI 主程序组装（页面注册机制）
- **所有核心模块**：ConfigService、ServiceRegistry、ProcessManager、HealthChecker、TaskScheduler、GpuMonitor、ResultManager
- Python 包：`gradio>=5.0`

## 10.1 仪表盘 (dashboard.py)

```python
# webui/pages/dashboard.py
import gradio as gr
from core import registry, scheduler, gpu_monitor, config
import datetime


def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        gr.Markdown("## 概览")
        
        # ── 定时刷新 ──
        refresh_timer = gr.Timer(value=10)
        
        # ── 服务摘要 ──
        gr.Markdown("### 服务状态")
        service_summary = gr.HTML("加载中...")
        
        # ── 最近任务 ──
        gr.Markdown("### 最近任务")
        recent_tasks = gr.HTML("加载中...")
        
        # ── GPU 概览 ──
        gr.Markdown("### GPU 概览")
        gpu_overview = gr.HTML("加载中...")
        
        # ── 刷新回调 ──
        def refresh_dashboard():
            # 服务摘要
            svc_list = registry.list_services()
            running = sum(1 for s in svc_list if s.runtime_state == "running")
            total = len(svc_list)
            svc_html = _build_service_summary(svc_list, running, total)
            
            # 最近任务
            tasks = scheduler.list_tasks(limit=5)
            task_html = _build_recent_tasks(tasks)
            
            # GPU 概览
            gpu = gpu_monitor.get_latest()
            gpu_html = _build_gpu_overview(gpu)
            
            return svc_html, task_html, gpu_html
        
        refresh_timer.tick(
            refresh_dashboard,
            outputs=[service_summary, recent_tasks, gpu_overview],
        )
    
    return page


def _build_service_summary(svc_list, running, total):
    """构建服务摘要 HTML。"""
    lines = [f"<p><b>{running}/{total}</b> 个服务正在运行</p><ul>"]
    for svc in svc_list:
        status_icon = {
            "running": "🟢", "unhealthy": "🟡", "starting": "🔵",
            "stopped": "⚪", "exited": "🔴", "stopping": "🔵",
        }.get(svc.runtime_state, "⚪")
        lines.append(f"<li>{status_icon} {svc.display_name} — {svc.runtime_state}</li>")
    lines.append("</ul>")
    return "".join(lines)


def _build_recent_tasks(tasks):
    """构建最近任务 HTML。"""
    if not tasks:
        return "<p>暂无任务</p>"
    lines = ["<table border='1' cellpadding='4' style='border-collapse:collapse; width:100%'>",
             "<tr><th>ID</th><th>服务</th><th>状态</th><th>时间</th></tr>"]
    for t in tasks:
        lines.append(f"<tr><td>{t['id'][:8]}...</td><td>{t['service_id']}</td>"
                     f"<td>{t['status']}</td><td>{t['created_at'][:19]}</td></tr>")
    lines.append("</table>")
    return "".join(lines)


def _build_gpu_overview(gpu):
    """构建 GPU 概览 HTML。"""
    if not gpu.available:
        return "<p>未检测到 NVIDIA GPU。</p>"
    lines = [f"<p>检测到 {len(gpu.snapshots)} 个 GPU</p><ul>"]
    for s in gpu.snapshots:
        mem_pct = int(s.memory_used_mb / max(s.memory_total_mb, 1) * 100)
        lines.append(
            f"<li>GPU {s.gpu_index}: {s.name} — "
            f"显存 {s.memory_used_mb}/{s.memory_total_mb} MiB ({mem_pct}%) — "
            f"利用率 {s.utilization_percent}% — {s.temperature_celsius}°C</li>"
        )
    lines.append("</ul>")
    return "".join(lines)
```

## 10.2 服务管理 (services.py)

```python
# webui/pages/services.py
import gradio as gr
from core import registry, process_manager, config


def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        refresh_timer = gr.Timer(value=5)
        
        gr.Markdown("## 服务管理")
        
        # ── 服务状态表 ──
        service_table = gr.HTML("加载中...")
        
        gr.Markdown("---")
        gr.Markdown("### 服务控制")
        
        # ── 控制区域 ──
        with gr.Row():
            service_selector = gr.Dropdown(
                label="选择服务",
                choices=[],  # 动态加载
                interactive=True,
                scale=2,
            )
            btn_start = gr.Button("启动", variant="primary", scale=1, min_width=80)
            btn_stop = gr.Button("停止", variant="stop", scale=1, min_width=80)
            btn_restart = gr.Button("重启", variant="secondary", scale=1, min_width=80)
        
        # ── 停止确认对话框 ──
        confirm_stop = gr.HTML(visible=False)
        with gr.Row():
            btn_confirm_stop = gr.Button("确认停止", variant="stop", visible=False, scale=1)
            btn_cancel_stop = gr.Button("取消", variant="secondary", visible=False, scale=1)
        
        # ── 状态与日志 ──
        status_msg = gr.Textbox(label="操作结果", interactive=False)
        log_viewer = gr.Textbox(label="服务日志 (最后 50 行)", lines=10, interactive=False)
        
        # ── 刷新回调 ──
        def refresh_services():
            svc_list = registry.list_services()
            html = _build_service_table(svc_list)
            choices = [(s.display_name, s.id) for s in svc_list]
            return html, gr.update(choices=choices)
        
        refresh_timer.tick(
            refresh_services,
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
            outputs=[confirm_stop, status_msg, btn_confirm_stop, btn_cancel_stop],
        )
        
        btn_confirm_stop.click(
            fn=lambda sid: _on_service_action(sid, "stop"),
            inputs=service_selector,
            outputs=status_msg,
        ).then(
            fn=lambda: (gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)),
            outputs=[confirm_stop, btn_confirm_stop, btn_cancel_stop],
        )
        
        btn_cancel_stop.click(
            fn=lambda: (gr.update(visible=False), "", gr.update(visible=False), gr.update(visible=False)),
            outputs=[confirm_stop, status_msg, btn_confirm_stop, btn_cancel_stop],
        )
        
        btn_restart.click(
            fn=lambda sid: _on_service_action(sid, "restart"),
            inputs=service_selector,
            outputs=status_msg,
        )
        
        # ── 查看日志 ──
        service_selector.change(
            fn=_on_select_service,
            inputs=service_selector,
            outputs=log_viewer,
        )
    
    return page


def _build_service_table(svc_list):
    """构建服务状态表 HTML。"""
    lines = ["<table border='1' cellpadding='6' style='border-collapse:collapse; width:100%'>",
             "<tr><th>ID</th><th>名称</th><th>类型</th><th>状态</th><th>GPU</th><th>URL</th></tr>"]
    for s in svc_list:
        status_display = {
            "running": "🟢 运行中", "stopped": "⚪ 已停止",
            "starting": "🔵 启动中", "unhealthy": "🟡 不健康",
            "stopping": "🔵 停止中", "exited": "🔴 已退出",
        }.get(s.runtime_state, s.runtime_state)
        
        gpu_str = ",".join(map(str, s.gpu_assignment)) if s.gpu_assignment else "不限"
        url_str = s.service_url or "(未配置)"
        
        lines.append(
            f"<tr><td>{s.id}</td><td>{s.display_name}</td>"
            f"<td>{s.model_type}</td><td>{status_display}</td>"
            f"<td>{gpu_str}</td><td>{url_str}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _on_service_action(service_id: str, action: str):
    if not service_id:
        return "请先选择一个服务"
    from core.process_manager import process_manager
    getattr(process_manager, action)(service_id)
    return f"已提交 {action} 请求: {service_id}"


def _on_stop_click(service_id: str):
    if not service_id:
        return [gr.update(visible=False), "请先选择一个服务", gr.update(visible=False), gr.update(visible=False)]
    
    from core import scheduler
    running = scheduler.get_running_tasks(service_id)
    if running:
        return [
            gr.update(value=f"<div style='color:orange'>⚠️ 服务 {service_id} 有 {len(running)} 个运行中的任务。停止将中断这些任务。</div>", visible=True),
            "",
            gr.update(visible=True),
            gr.update(visible=True),
        ]
    else:
        # 无运行任务，直接停止不确认
        _on_service_action(service_id, "stop")
        return [gr.update(visible=False), f"已提交停止请求: {service_id}", gr.update(visible=False), gr.update(visible=False)]


def _on_select_service(service_id: str):
    if not service_id:
        return "(选择服务后查看日志)"
    from core.process_manager import process_manager
    log = process_manager.tail_log(service_id)
    return log
```

> **注意**：`process_manager.tail_log()` 方法需要在 `ProcessManager` 中补充（见模块 5），读取 `data/logs/services/<id>/<timestamp>.log` 的最后 50 行。

## 10.3 任务管理 (tasks.py)

```python
# webui/pages/tasks.py
import gradio as gr
from core import registry, scheduler, result_mgr


def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        refresh_timer = gr.Timer(value=15)
        
        gr.Markdown("## 任务管理")
        
        # ── 筛选 ──
        with gr.Row():
            filter_service = gr.Dropdown(
                label="筛选服务",
                choices=[],  # 动态加载
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
        task_id_input = gr.Textbox(label="任务 ID", placeholder="输入任务 ID 查看详情")
        btn_view = gr.Button("查看", variant="secondary")
        
        with gr.Row():
            task_detail = gr.JSON(label="任务数据")
            result_files = gr.HTML(label="结果文件")
        
        # ── 刷新任务列表 ──
        def refresh_tasks(svc_filter, status_filter):
            services = registry.list_services()
            svc_choices = [("全部服务", "")] + [(s.display_name, s.id) for s in services]
            
            status = status_filter if status_filter != "全部" else None
            sid = svc_filter if svc_filter else None
            
            tasks = scheduler.list_tasks(service_id=sid, status=status)
            html = _build_task_list(tasks)
            return html, gr.update(choices=svc_choices)
        
        refresh_timer.tick(
            refresh_tasks,
            inputs=[filter_service, filter_status],
            outputs=[task_list, filter_service],
        )
        
        btn_refresh.click(
            refresh_tasks,
            inputs=[filter_service, filter_status],
            outputs=[task_list, filter_service],
        )
        
        # ── 查看任务详情 ──
        def view_task(task_id):
            if not task_id:
                return {}, ""
            task = scheduler.get_task(task_id)
            if not task:
                return {"error": "任务不存在"}, ""
            files = result_mgr.list_outputs(task_id)
            files_html = "<ul>" + "".join(f"<li>{f}</li>" for f in files) + "</ul>" if files else "<p>(无输出文件)</p>"
            return task, files_html
        
        btn_view.click(
            view_task,
            inputs=task_id_input,
            outputs=[task_detail, result_files],
        )
    
    return page


def _build_task_list(tasks):
    """构建任务列表 HTML。"""
    if not tasks:
        return "<p>暂无任务</p>"
    
    lines = ["<table border='1' cellpadding='4' style='border-collapse:collapse; width:100%'>",
             "<tr><th>ID</th><th>服务</th><th>模型</th><th>状态</th><th>创建时间</th><th>错误</th></tr>"]
    for t in tasks:
        error = t.get("error_summary", "") or ""
        lines.append(
            f"<tr><td>{t['id'][:8]}...</td><td>{t['service_id']}</td>"
            f"<td>{t['model_type']}</td><td>{t['status']}</td>"
            f"<td>{t['created_at'][:19]}</td>"
            f"<td style='color:red'>{error[:40]}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)
```

## 10.4 GPU 监控 (gpu.py)

```python
# webui/pages/gpu.py
import gradio as gr
from core import gpu_monitor, registry


def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        refresh_timer = gr.Timer(value=5)
        
        gr.Markdown("## GPU 监控")
        
        # ── GPU 仪表盘 ──
        gpu_dashboard = gr.HTML("加载中...")
        
        # ── GPU 推荐 ──
        gr.Markdown("### GPU 推荐")
        gr.Markdown("以下按可用显存从高到低排序，适用于新的任务分配。")
        
        recommendation = gr.HTML("加载中...")
        
        min_mem_input = gr.Slider(
            minimum=0, maximum=48, value=8, step=1,
            label="最低显存需求 (GB)",
        )
        
        def refresh_gpu(min_mem_gb):
            # 采集指标
            metrics = gpu_monitor.get_latest()
            gpu_html = _build_gpu_dashboard(metrics)
            
            # 推荐
            if metrics.available:
                recommended = gpu_monitor.recommend(min_memory_gb=int(min_mem_gb))
                rec_html = _build_recommendation(metrics, recommended)
            else:
                rec_html = "<p>GPU 监控不可用。</p>"
            
            return gpu_html, rec_html
        
        min_mem_input.change(refresh_gpu, inputs=min_mem_input, outputs=[gpu_dashboard, recommendation])
        refresh_timer.tick(refresh_gpu, inputs=min_mem_input, outputs=[gpu_dashboard, recommendation])
    
    return page


def _build_gpu_dashboard(metrics):
    """构建 GPU 仪表盘 HTML。"""
    if not metrics.available:
        return "<div style='padding:20px;text-align:center;color:#888'><h3>未检测到 NVIDIA GPU</h3><p>GPU 监控功能不可用。</p></div>"
    
    cards = []
    for s in metrics.snapshots:
        mem_pct = int(s.memory_used_mb / max(s.memory_total_mb, 1) * 100)
        cards.append(f"""
        <div style='border:1px solid #ddd;border-radius:8px;padding:12px;margin:8px 0;
                    background:#f9f9f9;display:inline-block;width:30%;min-width:280px;vertical-align:top;margin-right:10px;'>
            <h4>GPU {s.gpu_index}: {s.name}</h4>
            <table style='width:100%;font-size:14px;'>
                <tr><td>显存</td><td>{s.memory_used_mb} / {s.memory_total_mb} MiB ({mem_pct}%)</td></tr>
                <tr><td>GPU 利用率</td><td>{s.utilization_percent}%</td></tr>
                <tr><td>温度</td><td>{s.temperature_celsius}°C</td></tr>
                <tr><td>功耗</td><td>{s.power_milliwatts / 1000:.1f} W</td></tr>
                <tr><td>进程</td><td>{len(s.processes)} 个</td></tr>
            </table>
        </div>""")
    
    return "<div>" + "".join(cards) + "</div>" + \
           f"<p style='color:#888;font-size:12px'>更新于 {metrics.updated_at[:19]}</p>"


def _build_recommendation(metrics, recommended):
    if not recommended:
        return "<p>没有满足最低显存要求的 GPU。</p>"
    
    items = []
    for idx, gpu_idx in enumerate(recommended):
        s = next((s for s in metrics.snapshots if s.gpu_index == gpu_idx), None)
        if not s:
            continue
        tag = "🟢 推荐" if idx == 0 else f"{idx+1}. "
        items.append(f"<li>{tag} GPU {gpu_idx} — 可用显存 {s.memory_free_mb} MiB, 利用率 {s.utilization_percent}%</li>")
    
    return "<ol>" + "".join(items) + "</ol>"
```

## 10.5 配置 (config.py)

```python
# webui/pages/config.py
import gradio as gr
import yaml
from core import config
from core.config_service import ConfigError


def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        gr.Markdown("## 配置管理")
        
        gr.Markdown("""
        编辑 `config/services.yaml` 的完整内容。
        修改后点击保存，系统将校验并持久化。
        """)
        
        # ── YAML 编辑器 ──
        yaml_editor = gr.Textbox(
            label="services.yaml",
            lines=25,
            max_lines=40,
            value="",  # 从磁盘加载
            interactive=True,
        )
        
        # ── 操作按钮 ──
        with gr.Row():
            btn_load = gr.Button("重新加载", variant="secondary")
            btn_save = gr.Button("保存", variant="primary")
        
        save_status = gr.Textbox(label="状态", interactive=False)
        error_display = gr.Textbox(label="校验错误", lines=5, interactive=False)
        
        # ── 加载 ──
        def load_yaml():
            services = config.get_services_list()
            payload = {"services": services}
            yaml_text = yaml.dump(payload, default_flow_style=False, allow_unicode=True)
            return yaml_text, "", ""
        
        btn_load.click(load_yaml, outputs=[yaml_editor, save_status, error_display])
        
        # ── 保存 ──
        def save_yaml(yaml_text: str):
            try:
                parsed = yaml.safe_load(yaml_text)
                if not isinstance(parsed, dict):
                    raise ConfigError("YAML 必须是一个字典（从 services: 开始）")
                
                services_list = parsed.get("services", [])
                config.save_services_config(services_list)
                
                # 重新加载 ServiceRegistry
                from core import registry
                registry.load_from_config(services_list)
                
                return "保存成功", ""
            except yaml.YAMLError as e:
                return "", f"YAML 解析错误: {e}"
            except ConfigError as e:
                return "", f"配置校验错误: {e}"
        
        btn_save.click(
            save_yaml,
            inputs=yaml_editor,
            outputs=[save_status, error_display],
        )
    
    return page
```

## 10.6 模型入口页面（占位）

所有四个模型入口页面结构相同，仅标题和描述不同。

### stable_diffusion.py

```python
# webui/pages/stable_diffusion.py
import gradio as gr
from adapters import get_adapter
from core import registry, scheduler, result_mgr, gpu_monitor


def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        gr.Markdown("## Stable Diffusion")
        
        # 检查适配器可用性
        try:
            adapter = get_adapter("stable-diffusion")
            has_adapter = True
        except ValueError:
            has_adapter = False
        
        if not has_adapter:
            gr.Markdown("> **适配器未注册。** 请检查适配器模块加载。")
            return page
        
        # ── 占位提示 ──
        gr.Markdown(
            "> **Stable Diffusion 适配器当前为占位状态。** "
            "配置并启动服务后，在此页面提交推理任务。"
        )
        
        # ── 服务选择 ──
        svc_list = registry.get_by_model_type("stable-diffusion")
        service_choices = [(s.display_name, s.id) for s in svc_list]
        
        with gr.Row():
            service_selector = gr.Dropdown(
                label="服务",
                choices=service_choices,
                interactive=True,
                scale=2,
            )
            gpu_selector = gr.Dropdown(
                label="目标 GPU (推荐)",
                choices=[],  # 动态加载
                interactive=True,
                scale=1,
            )
        
        # ── 参数区 ──
        prompt = gr.Textbox(label="提示词 (Prompt)", lines=3, placeholder="输入提示词...")
        with gr.Row():
            width = gr.Slider(256, 2048, value=512, step=64, label="宽度")
            height = gr.Slider(256, 2048, value=512, step=64, label="高度")
        
        with gr.Row():
            steps = gr.Slider(1, 150, value=20, step=1, label="采样步数")
            cfg_scale = gr.Slider(1.0, 30.0, value=7.0, step=0.5, label="CFG 缩放")
        
        btn_submit = gr.Button("提交任务", variant="primary")
        
        # ── 结果 ──
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.Textbox(label="状态", interactive=False)
        error_output = gr.Textbox(label="错误信息", lines=3, interactive=False)
        
        # ── GPU 选择更新 ──
        def update_gpu_selector():
            metrics = gpu_monitor.get_latest()
            if not metrics.available:
                return gr.update(choices=[], value="")
            recommended = gpu_monitor.recommend()
            choices = [(f"GPU {s.gpu_index} — 空闲 {s.memory_free_mb} MiB", str(s.gpu_index))
                       for s in metrics.snapshots]
            value = str(recommended[0]) if recommended else ""
            return gr.update(choices=choices, value=value)
        
        btn_submit.click(
            fn=update_gpu_selector,
            outputs=gpu_selector,
        ).then(
            fn=_on_submit_sd,
            inputs=[service_selector, gpu_selector, prompt, width, height, steps, cfg_scale],
            outputs=[task_id_output, status_output, error_output],
        )
    
    return page


def _on_submit_sd(service_id, gpu_idx, prompt, width, height, steps, cfg_scale):
    if not service_id:
        return "", "错误", "请选择服务"
    
    task_id = scheduler.create_task(
        service_id=service_id,
        model_type="stable-diffusion",
        adapter_name="StableDiffusionAdapter",
        request_payload={
            "prompt": prompt,
            "width": width, "height": height,
            "steps": steps, "cfg_scale": cfg_scale,
        },
        target_gpu=[int(gpu_idx)] if gpu_idx else None,
    )
    
    result_mgr.ensure_task_dir(task_id)
    result_mgr.save_request(task_id, {
        "prompt": prompt,
        "width": width, "height": height,
        "steps": steps, "cfg_scale": cfg_scale,
    })
    
    try:
        adapter = get_adapter("stable-diffusion")
        service_url = registry.get(service_id).service_url
        adapter.submit(service_url, {"prompt": prompt}, target_gpu=[int(gpu_idx)] if gpu_idx else None)
        return task_id, "完成", ""
    except NotImplementedError as e:
        scheduler.update_task_status(task_id, "failed", error_summary=str(e))
        result_mgr.save_log(task_id, "error.log", str(e))
        return task_id, "失败", str(e)
    except Exception as e:
        scheduler.update_task_status(task_id, "failed", error_summary=f"提交失败: {e}")
        return task_id, "错误", str(e)
```

### qwen3_asr.py / whisperx.py / fastwhisper.py

结构同上，仅替换：
- `model_type` 参数（`"qwen3-asr"` / `"whisperx"` / `"fastwhisper"`）
- `adapter_name` 参数（`"Qwen3ASRAdapter"` / `"WhisperXAdapter"` / `"FastWhisperAdapter"`）
- 标题和描述文本
- 预留的参数区（Qwen3ASR 标注 audio 输入、WhisperX 标注 file 输入等）

```python
# webui/pages/qwen3_asr.py 的 create_page()
# 与 stable_diffusion.py 的区别:
# - 标题: "Qwen3 ASR"
# - 预留参数: audio 输入、语言选项、时间戳
# - 参数当前都标注 "(预留 — 后续阶段实现)"

# webui/pages/whisperx.py 的 create_page()
# - 标题: "WhisperX"
# - 预留参数: audio/file 输入

# webui/pages/fastwhisper.py 的 create_page()
# - 标题: "FastWhisper"
# - 预留参数: audio/file 输入
```

可以通过一个共享的模型入口页面模板来减少重复代码，但第一阶段为了清晰度，保持四个文件各自独立。

## 组件目录

### components/ 结构

```python
# webui/components/service_table.py
# 供 services.py 使用的服务状态表组件

# webui/components/task_list.py
# 供 tasks.py 使用的任务列表组件

# webui/components/gpu_dashboard.py
# 供 gpu.py 使用的 GPU 仪表盘组件

# webui/components/config_editor.py
# 供 config.py 使用的 YAML 编辑器组件

# webui/components/error_display.py
# 错误信息展示组件
```

第一阶段中，这些组件大多还保留在每个页面文件的函数中（`_build_service_table`、`_build_task_list` 等）。第二阶段若有多个页面复用同样的 UI 模式，再抽取到 `components/`。

## 集成点

模块不要求在 `main.py` 中有额外的集成代码，所有页面通过 `webui/app.py` 的 `create_app()` 统一注册和渲染。

## 验收标准

1. **仪表盘**：显示服务摘要统计、最近 5 条任务、GPU 概览
2. **仪表盘**：每 10 秒自动刷新
3. **服务管理**：显示服务列表（ID、名称、类型、状态、GPU、URL）
4. **服务管理**：选择服务后可启动、停止、重启
5. **服务管理**：停止有运行中任务的服务时弹出确认
6. **服务管理**：选择服务后显示日志尾部
7. **任务管理**：显示任务列表，可按服务和状态筛选
8. **任务管理**：输入任务 ID 可查看详情和输出文件
9. **GPU 监控**：每 5 秒刷新，显示每个 GPU 的指标卡片
10. **GPU 监控**：按最低显存需求返回 GPU 推荐列表
11. **配置**：加载当前 services.yaml 到编辑器
12. **配置**：保存时校验 YAML 和服务定义规则
13. **配置**：校验失败时不覆盖文件并显示错误
14. **模型入口页面**：显示适配器占位提示
15. **模型入口页面**：选择服务后提交任务，返回失败状态（占位适配器）
