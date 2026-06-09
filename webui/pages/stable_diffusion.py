# webui/pages/stable_diffusion.py — Stable Diffusion 模型入口页面（占位）

import gradio as gr
from adapters import get_adapter
from core import registry, scheduler, result_mgr, gpu_monitor


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 Stable Diffusion 模型入口标签页。"""
    gr.Markdown("## Stable Diffusion")

    # 检查适配器
    try:
        get_adapter("stable-diffusion")
    except ValueError:
        gr.Markdown("> **适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")

    gr.Markdown(
        "> **Stable Diffusion 适配器当前为占位状态。** "
        "配置并启动服务后，在此页面提交推理任务。"
        "当前提交的任务会记录到任务管理，但不会实际执行推理。"
    )

    # 服务选择
    svc_list = registry.get_by_model_type("stable-diffusion")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    service_selector = gr.Dropdown(
        label="服务",
        choices=service_choices,
        interactive=True,
        scale=2,
    )

    # GPU 选择
    metrics = gpu_monitor.get_latest()
    if metrics.available:
        recommended = gpu_monitor.recommend()
        gpu_choices = [
            (f"GPU {s.gpu_index} — 空闲 {s.memory_free_mb} MiB", str(s.gpu_index))
            for s in metrics.snapshots
        ]
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

    # 模型参数
    prompt = gr.Textbox(
        label="提示词 (Prompt)", lines=3, placeholder="输入提示词...",
    )
    with gr.Row():
        width = gr.Slider(256, 2048, value=512, step=64, label="宽度")
        height = gr.Slider(256, 2048, value=512, step=64, label="高度")
    with gr.Row():
        steps = gr.Slider(1, 150, value=20, step=1, label="采样步数")
        cfg_scale = gr.Slider(
            1.0, 30.0, value=7.0, step=0.5, label="CFG 缩放",
        )

    btn_submit = gr.Button("提交任务", variant="primary")

    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.Textbox(label="状态", interactive=False)
    error_output = gr.Textbox(label="错误信息", lines=3, interactive=False)

    # 提交回调
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
            "prompt": prompt_text, "width": w, "height": h,
            "steps": st, "cfg_scale": cfg,
        })

        try:
            adapter = get_adapter("stable-diffusion")
            # 占位适配器会抛出 NotImplementedError
            import asyncio
            loop = asyncio.new_event_loop()
            adapter.submit(
                service_url="",
                payload={"prompt": prompt_text},
                target_gpu=[int(gpu_idx)] if gpu_idx else None,
            )
            loop.close()
            return task_id, "完成", ""
        except NotImplementedError as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=str(e),
            )
            result_mgr.save_log(task_id, "error.log", str(e))
            return task_id, "失败", str(e)
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"提交失败: {e}",
            )
            return task_id, "错误", str(e)

    btn_submit.click(
        fn=on_submit,
        inputs=[
            service_selector, gpu_selector, prompt,
            width, height, steps, cfg_scale,
        ],
        outputs=[task_id_output, status_output, error_output],
    )

    return gr.HTML("")
