# webui/pages/stable_diffusion.py — Stable Diffusion 模型入口页面（Phase 3 完整实现）

import asyncio
import base64
import io
import gradio as gr
from adapters import get_adapter
from core import registry, scheduler, result_mgr, gpu_monitor
from webui.components.error_display import format_error_message
from webui.components.progress_indicator import build_progress_bar, build_status_badge


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 Stable Diffusion 标签页。"""
    gr.Markdown("## 🎨 Stable Diffusion 图像生成")

    try:
        adapter = get_adapter("stable-diffusion")
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。**")
        return gr.HTML("")

    # 所有适配器在 Phase 4 均为真实 HTTP 客户端实现，无需 HTTP 探活
    # 服务可用性由后台 HealthChecker 线程持续探测，启动时无需预检
    gr.Markdown(
        "> **ℹ️ Stable Diffusion 适配器已就绪。** 配置并启动 SD 服务后即可使用。\n"
        "> 启动方式: `python services/stable_diffusion_service.py --port 17860`"
    )

    svc_list = registry.get_by_model_type("stable-diffusion")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    gr.Markdown(
        f"*{len(svc_list)} 个 SD 服务可用*" if svc_list
        else "*暂无 SD 服务*"
    )

    # ── 服务 + GPU 选择 ──
    with gr.Row():
        service_selector = gr.Dropdown(
            label="服务", choices=service_choices, interactive=True, scale=2,
        )
        metrics = gpu_monitor.get_latest()
        if metrics.available:
            rec = gpu_monitor.recommend(min_memory_gb=4)
            gpu_choices = [
                (f"GPU {s.gpu_index} — 空闲 {s.memory_free_mb} MiB", str(s.gpu_index))
                for s in metrics.snapshots
            ]
            default_gpu = str(rec[0]) if rec else ""
        else:
            gpu_choices = [("自动", "")]
            default_gpu = ""
        gpu_selector = gr.Dropdown(
            label="目标 GPU", choices=gpu_choices, value=default_gpu,
            interactive=True, scale=1,
        )

    # ── 参数 ──
    gr.Markdown("### 参数设置")
    prompt = gr.Textbox(
        label="提示词 (Prompt)", lines=3,
        placeholder="a beautiful landscape, highly detailed, 8k...",
    )
    negative_prompt = gr.Textbox(
        label="反向提示词 (Negative Prompt)", lines=2,
        placeholder="ugly, blurry, low quality...",
    )

    with gr.Row():
        width = gr.Slider(256, 2048, value=512, step=64, label="宽度")
        height = gr.Slider(256, 2048, value=512, step=64, label="高度")
    with gr.Row():
        steps = gr.Slider(1, 150, value=20, step=1, label="采样步数")
        cfg_scale = gr.Slider(1.0, 30.0, value=7.0, step=0.5, label="CFG 缩放")
    with gr.Row():
        seed = gr.Number(value=-1, label="种子 (-1=随机)", precision=0)
        batch_size = gr.Slider(1, 4, value=1, step=1, label="批次大小")

    btn_submit = gr.Button("🎨 生成图像", variant="primary", size="lg")

    # ── 输出 ──
    gr.Markdown("---")
    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False, scale=2)
        status_output = gr.HTML(label="状态", value="")

    progress_output = gr.HTML(label="")
    error_output = gr.HTML(label="")

    # 图像画廊
    gr.Markdown("### 🖼️ 生成结果")
    image_gallery = gr.Gallery(
        label="", columns=2, rows=2, height="auto",
    )
    seed_output = gr.Textbox(label="实际种子", interactive=False)

    # ── 提交回调 ──
    def on_submit(svc_id, gpu_idx, prompt_text, neg_prompt, w, h, st, cfg, sd, bs):
        if not svc_id:
            return (
                "", "", "",
                format_error_message("请先选择服务",
                    suggestion="在服务管理标签页配置并启动 SD 服务"),
                [], "",
            )
        if not prompt_text.strip():
            return (
                "", "", "",
                format_error_message("请填写提示词"),
                [], "",
            )

        task_id = scheduler.create_task(
            service_id=svc_id,
            model_type="stable-diffusion",
            adapter_name="StableDiffusionAdapter",
            request_payload={
                "prompt": prompt_text,
                "negative_prompt": neg_prompt,
                "width": w, "height": h,
                "steps": st, "cfg_scale": cfg,
                "seed": int(sd), "batch_size": int(bs),
            },
            target_gpu=[int(gpu_idx)] if gpu_idx else None,
            max_retries=2,
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {
            "prompt": prompt_text, "width": w, "height": h,
            "steps": st, "cfg_scale": cfg, "seed": int(sd),
        })

        try:
            adapter = get_adapter("stable-diffusion")
            service = registry.get(svc_id)
            service_url = service.service_url if service else ""

            if not service_url:
                raise ValueError("服务 URL 未配置")

            # 更新为运行中
            scheduler.update_task_status(task_id, "running")
            status_html = (
                build_status_badge("running")
                + build_progress_bar(5, "正在提交任务...")
            )

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                adapter.submit(
                    service_url=service_url,
                    payload={
                        "prompt": prompt_text,
                        "negative_prompt": neg_prompt,
                        "width": w, "height": h,
                        "steps": st, "cfg_scale": cfg,
                        "seed": int(sd), "batch_size": int(bs),
                    },
                    target_gpu=[int(gpu_idx)] if gpu_idx else None,
                )
            )
            loop.close()

            # 轮询等待结果
            import time
            for i in range(60):
                loop = asyncio.new_event_loop()
                status = loop.run_until_complete(
                    adapter.poll_status(service_url, result)
                )
                loop.close()

                progress = status.get("progress", 0) or 0
                status_html = (
                    build_status_badge(status.get("status", "running"))
                    + build_progress_bar(progress, f"生成中... ({i * 2}s)")
                )

                if status["status"] in ("completed", "failed"):
                    break
                time.sleep(2)

            if status["status"] == "completed":
                result_data = status.get("result", {})
                images_b64 = result_data.get("images", [])
                actual_seed = result_data.get("seed", int(sd))

                # 保存到 result_mgr
                image_paths = []
                for idx, img_b64 in enumerate(images_b64):
                    img_data = base64.b64decode(img_b64)
                    out_path = result_mgr.get_output_path(
                        task_id, f"result_{idx}.png"
                    )
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(img_data)
                    image_paths.append(f"outputs/result_{idx}.png")

                scheduler.update_task_status(
                    task_id, "completed",
                    result_paths=image_paths,
                )
                result_mgr.save_response(task_id, {
                    "seed": actual_seed,
                    "images": image_paths,
                    "status": "completed",
                })

                # 解码为 Gradio Gallery 格式
                import numpy as np
                from PIL import Image
                gallery_imgs = []
                for img_b64 in images_b64:
                    img_bytes = base64.b64decode(img_b64)
                    img = Image.open(io.BytesIO(img_bytes))
                    gallery_imgs.append(np.array(img))

                return (
                    task_id, build_status_badge("completed"),
                    "", "",
                    gallery_imgs, f"种子: {actual_seed}",
                )
            else:
                error_msg = status.get("error", "生成失败")
                scheduler.update_task_status(
                    task_id, "failed", error_summary=error_msg,
                )
                return (
                    task_id, build_status_badge("failed"),
                    "",
                    format_error_message(error_msg, task_id=task_id,
                        suggestion="请检查 SD 服务日志"),
                    [], "",
                )

        except NotImplementedError as e:
            scheduler.update_task_status(task_id, "failed", error_summary=str(e))
            return (
                task_id, build_status_badge("failed"),
                "",
                format_error_message("SD 适配器尚未实现",
                    suggestion="启动服务: python services/stable_diffusion_service.py",
                    details=str(e)),
                [], "",
            )
        except ConnectionError as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"连接失败: {e}",
            )
            return (
                task_id, build_status_badge("failed"),
                "",
                format_error_message("无法连接到 SD 服务", service_id=svc_id,
                    suggestion="请确认服务已启动且 URL 配置正确", details=str(e)),
                [], "",
            )
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"提交失败: {e}",
            )
            return (
                task_id, build_status_badge("failed"),
                "",
                format_error_message("请求处理失败", task_id=task_id,
                    suggestion="请查看任务管理标签页", details=str(e)),
                [], "",
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[
            service_selector, gpu_selector, prompt, negative_prompt,
            width, height, steps, cfg_scale, seed, batch_size,
        ],
        outputs=[
            task_id_output, status_output, progress_output, error_output,
            image_gallery, seed_output,
        ],
    )

    return gr.HTML("")


import os  # noqa: E402
