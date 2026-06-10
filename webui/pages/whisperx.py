# webui/pages/whisperx.py — WhisperX 模型入口页面（Phase 3 完整实现）

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


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 WhisperX 模型入口标签页。"""
    gr.Markdown("## 🎙️ WhisperX 语音识别 (说话人识别)")

    try:
        get_adapter("whisperx")
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。**")
        return gr.HTML("")

    gr.Markdown(
        "> **WhisperX** 支持词级时间戳对齐和说话人识别 (diarization)。"
        "使用 whisper-large-v3 模型，适合需要精确时间轴和多人对话转录的场景。"
    )

    # 服务选择
    svc_list = registry.get_by_model_type("whisperx")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    gr.Markdown(f"*{len(svc_list)} 个 WhisperX 服务可用*" if svc_list else "*暂无服务*")

    service_selector = gr.Dropdown(
        label="服务", choices=service_choices, interactive=True, scale=2,
    )

    # ── 音频输入 ──
    with gr.Row():
        audio_input = gr.Audio(
            label="音频输入",
            type="numpy",
            sources=["upload", "microphone"],
            scale=2,
        )
        with gr.Column(scale=1):
            language_selector = gr.Dropdown(
                label="语种", choices=SUPPORTED_LANGUAGES, value="Auto",
                interactive=True,
            )
            enable_diarization = gr.Checkbox(
                label="启用说话人识别 (Diarization)", value=False,
            )
            return_srt = gr.Checkbox(label="返回 SRT 字幕", value=True)
            return_timestamps = gr.Checkbox(label="返回时间戳", value=True)

    btn_submit = gr.Button("🎙️ 开始转录", variant="primary", size="lg")

    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False, scale=2)
        status_output = gr.HTML(label="状态", value="")

    error_output = gr.HTML(label="")

    gr.Markdown("---")
    gr.Markdown("### 📝 识别结果")
    result_text = gr.Textbox(label="转录文本", lines=6, interactive=False)
    srt_output = gr.Textbox(
        label="SRT 字幕", lines=8, interactive=False, visible=False,
    )

    return_srt.change(
        fn=lambda v: gr.update(visible=v),
        inputs=return_srt, outputs=srt_output,
    )

    def on_submit(svc_id, audio, language, diarization, with_srt, with_ts):
        if not svc_id:
            return "", "", format_error_message("请先选择服务"), "", ""
        if audio is None:
            return "", "", format_error_message("请上传音频文件"), "", ""

        task_id = scheduler.create_task(
            service_id=svc_id, model_type="whisperx",
            adapter_name="WhisperXAdapter",
            request_payload={
                "language": language,
                "enable_diarization": diarization,
                "return_timestamps": with_ts,
                "return_srt": with_srt,
            },
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {
            "language": language, "enable_diarization": diarization,
            "return_timestamps": with_ts, "return_srt": with_srt,
        })

        try:
            adapter = get_adapter("whisperx")
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
                        "audio": audio_b64,
                        "language": language,
                        "enable_diarization": diarization,
                        "return_timestamps": with_ts,
                        "return_srt": with_srt,
                    },
                )
            )
            loop.close()

            scheduler.update_task_status(task_id, "running")

            import time
            for _ in range(120):
                loop = asyncio.new_event_loop()
                status = loop.run_until_complete(
                    adapter.poll_status(service_url, result)
                )
                loop.close()
                if status["status"] in ("completed", "failed"):
                    break
                time.sleep(2)

            if status["status"] == "completed":
                r = status.get("result", {})
                text = r.get("text", "")
                srt = r.get("srt", "")
                scheduler.update_task_status(task_id, "completed")
                result_mgr.save_response(task_id, {"text": text, "srt": srt})
                result_mgr.save_log(task_id, "transcript.txt", text)
                return (
                    task_id, build_status_badge("completed"), "",
                    text, srt if with_srt else "",
                )
            else:
                err = status.get("error", "转录失败")
                scheduler.update_task_status(task_id, "failed", error_summary=err)
                return (
                    task_id, build_status_badge("failed"),
                    format_error_message(err, task_id=task_id),
                    "", "",
                )

        except NotImplementedError as e:
            scheduler.update_task_status(task_id, "failed", error_summary=str(e))
            return (
                task_id, build_status_badge("failed"),
                format_error_message("WhisperX 适配器尚未实现", details=str(e)),
                "", "",
            )
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=str(e),
            )
            return (
                task_id, build_status_badge("failed"),
                format_error_message("请求失败", details=str(e)),
                "", "",
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[
            service_selector, audio_input, language_selector,
            enable_diarization, return_srt, return_timestamps,
        ],
        outputs=[
            task_id_output, status_output, error_output,
            result_text, srt_output,
        ],
    )

    return gr.HTML("")
