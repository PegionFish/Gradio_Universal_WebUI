# webui/pages/fastwhisper.py — FastWhisper 模型入口页面（Phase 3 完整实现）

import asyncio
import gradio as gr
from adapters import get_adapter
from core import registry, scheduler, result_mgr, gpu_monitor
from webui.components.error_display import format_error_message
from webui.components.progress_indicator import build_status_badge


SUPPORTED_LANGUAGES = [
    "Auto", "zh", "en", "ja", "ko", "yue",
    "de", "fr", "es", "it", "pt", "ru", "ar",
]
MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 FastWhisper 模型入口标签页。"""
    gr.Markdown("## ⚡ FastWhisper 极速语音识别 (CTranslate2)")

    try:
        get_adapter("fastwhisper")
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。**")
        return gr.HTML("")

    gr.Markdown(
        "> **FastWhisper** 使用 CTranslate2 后端，推理速度比原始 Whisper 快 4-8 倍。"
        "适合实时转录和大量音频批处理。"
    )

    svc_list = registry.get_by_model_type("fastwhisper")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    gr.Markdown(f"*{len(svc_list)} 个 FastWhisper 服务可用*" if svc_list else "*暂无服务*")

    service_selector = gr.Dropdown(
        label="服务", choices=service_choices, interactive=True, scale=2,
    )

    # ── 音频输入 + 参数 ──
    with gr.Row():
        audio_input = gr.Audio(
            label="音频输入", type="numpy",
            sources=["upload", "microphone"], scale=2,
        )
        with gr.Column(scale=1):
            language_selector = gr.Dropdown(
                label="语种", choices=SUPPORTED_LANGUAGES, value="Auto",
                interactive=True,
            )
            model_selector = gr.Dropdown(
                label="模型大小", choices=MODEL_SIZES, value="large-v3",
                interactive=True,
            )
            beam_size = gr.Slider(
                1, 10, value=5, step=1, label="Beam Size",
            )
            vad_filter = gr.Checkbox(
                label="VAD 过滤 (自动移除静音)", value=True,
            )
            return_srt = gr.Checkbox(label="返回 SRT 字幕", value=True)

    btn_submit = gr.Button("⚡ 快速转录", variant="primary", size="lg")

    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False, scale=2)
        status_output = gr.HTML(label="状态", value="")

    error_output = gr.HTML(label="")

    gr.Markdown("---")
    gr.Markdown("### 📝 识别结果")

    with gr.Row():
        result_text = gr.Textbox(
            label="转录文本", lines=6, interactive=False, scale=2,
        )
        srt_output = gr.Textbox(
            label="SRT 字幕", lines=8, interactive=False, visible=False, scale=1,
        )
        # 性能指标
        perf_output = gr.HTML(label="性能", value="")

    return_srt.change(
        fn=lambda v: gr.update(visible=v),
        inputs=return_srt, outputs=srt_output,
    )

    def on_submit(svc_id, audio, language, model, beam, use_vad, with_srt):
        if not svc_id:
            return "", "", format_error_message("请先选择服务"), "", "", ""
        if audio is None:
            return "", "", format_error_message("请上传音频文件"), "", "", ""

        import time as time_mod
        start_time = time_mod.time()

        task_id = scheduler.create_task(
            service_id=svc_id, model_type="fastwhisper",
            adapter_name="FastWhisperAdapter",
            request_payload={
                "language": language, "model": model,
                "beam_size": beam, "vad_filter": use_vad,
                "return_srt": with_srt,
            },
            max_retries=2,
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {
            "language": language, "model": model,
            "beam_size": beam, "vad_filter": use_vad, "return_srt": with_srt,
        })

        try:
            adapter = get_adapter("fastwhisper")
            service = registry.get(svc_id)
            service_url = service.service_url if service else ""

            if not service_url:
                raise ValueError("服务 URL 未配置")

            import numpy as np
            import base64
            import io
            from scipy.io.wavfile import write as wav_write

            if isinstance(audio, tuple):
                sr, data_wav = audio
            else:
                sr, data_wav = audio[0], audio[1]
            if data_wav.ndim > 1:
                data_wav = data_wav.mean(axis=1)
            data_wav = data_wav.astype(np.float32)

            buf = io.BytesIO()
            wav_write(buf, sr, data_wav)
            audio_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                adapter.submit(
                    service_url=service_url,
                    payload={
                        "audio": audio_b64, "language": language,
                        "model": model, "beam_size": beam,
                        "vad_filter": use_vad, "return_srt": with_srt,
                    },
                )
            )
            loop.close()

            scheduler.update_task_status(task_id, "running")

            for _ in range(120):
                loop = asyncio.new_event_loop()
                status = loop.run_until_complete(
                    adapter.poll_status(service_url, result)
                )
                loop.close()
                if status["status"] in ("completed", "failed"):
                    break
                time_mod.sleep(1.5)

            elapsed = time_mod.time() - start_time

            if status["status"] == "completed":
                r = status.get("result", {})
                text = r.get("text", "")
                srt = r.get("srt", "")
                perf = (
                    f"<span style='color:#4caf50'>✅</span> "
                    f"耗时 {elapsed:.1f}s | "
                    f"模型: {model} | beam={beam}"
                )
                scheduler.update_task_status(task_id, "completed")
                result_mgr.save_response(task_id, {"text": text, "srt": srt})
                result_mgr.save_log(task_id, "transcript.txt", text)
                return (
                    task_id, build_status_badge("completed"), "",
                    text, srt if with_srt else "", perf,
                )
            else:
                err = status.get("error", "转录失败")
                scheduler.update_task_status(task_id, "failed", error_summary=err)
                return (
                    task_id, build_status_badge("failed"),
                    format_error_message(err, task_id=task_id),
                    "", "", "",
                )

        except NotImplementedError as e:
            scheduler.update_task_status(task_id, "failed", error_summary=str(e))
            return (
                task_id, build_status_badge("failed"),
                format_error_message("FastWhisper 适配器尚未实现", details=str(e)),
                "", "", "",
            )
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=str(e),
            )
            return (
                task_id, build_status_badge("failed"),
                format_error_message("请求失败", details=str(e)),
                "", "", "",
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[
            service_selector, audio_input, language_selector,
            model_selector, beam_size, vad_filter, return_srt,
        ],
        outputs=[
            task_id_output, status_output, error_output,
            result_text, srt_output, perf_output,
        ],
    )

    return gr.HTML("")
