# webui/pages/qwen3_tts.py — Qwen3 TTS 文字转语音模型入口页面

import asyncio
import base64
import io
import logging
import tempfile

import gradio as gr
import numpy as np

from adapters import get_adapter
from core import registry, scheduler, result_mgr
from webui.components.error_display import format_error_message
from webui.components.progress_indicator import build_status_badge

logger = logging.getLogger(__name__)

LANGUAGES = [
    "Chinese", "English", "Japanese", "Korean",
    "German", "French", "Russian", "Portuguese",
    "Spanish", "Italian", "Auto",
]

SPEAKERS = [
    "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric",
    "Ryan", "Aiden", "Ono_Anna", "Sohee",
]


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## 🗣️ Qwen3 TTS 文字转语音")

    try:
        adapter = get_adapter("qwen3-tts")
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")

    gr.Markdown("""
    > **ℹ️ Qwen3 TTS 适配器已就绪。** 配置并启动 TTS 服务后，即可使用文字转语音功能。
    >
    > **快速开始：**
    > 1. 在<em>服务管理</em>标签页添加一个 `qwen3-tts` 类型的服务
    > 2. 使用 `services/qwen3_tts_service.py --models-dir /path/to/models` 启动服务
    > 3. 返回此页面选择模式并输入文本
    """)

    svc_list = registry.get_by_model_type("qwen3-tts")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    service_info = (
        f"已找到 {len(svc_list)} 个 TTS 服务"
        if svc_list else "暂无 TTS 服务（请在服务管理中添加）"
    )
    gr.Markdown(f"*{service_info}*")

    service_selector = gr.Dropdown(
        label="服务",
        choices=service_choices,
        interactive=True,
    )

    with gr.Tabs():
        with gr.Tab("声音设计 (Voice Design)"):
            gr.Markdown('通过自然语言描述（如"甜美的萝莉音"）创建定制化音色。')
            with gr.Row():
                with gr.Column():
                    vd_text = gr.Textbox(
                        label="文本",
                        lines=3,
                        placeholder="请输入要合成的文本...",
                    )
                    vd_lang = gr.Dropdown(
                        label="语言", choices=LANGUAGES, value="Auto",
                    )
                    vd_instruct = gr.Textbox(
                        label="声音描述",
                        placeholder="例如：甜美的萝莉音",
                        lines=2,
                    )
                    vd_btn = gr.Button("🎨 开始生成", variant="primary")
                with gr.Column():
                    vd_audio = gr.Audio(label="生成音频")
                    vd_status = gr.HTML("")

        with gr.Tab("语音克隆 (Voice Clone)"):
            gr.Markdown("基于参考音频和文本，复刻目标人物的声音。")
            with gr.Row():
                with gr.Column():
                    vc_text = gr.Textbox(
                        label="文本",
                        lines=3,
                        placeholder="请输入要合成的文本...",
                    )
                    vc_lang = gr.Dropdown(
                        label="语言", choices=LANGUAGES, value="Auto",
                    )
                    vc_ref_audio = gr.Audio(
                        label="参考音频", type="filepath",
                    )
                    vc_ref_text = gr.Textbox(
                        label="参考文本",
                        placeholder="参考音频里的台词（留空则使用零样本克隆）",
                    )
                    vc_btn = gr.Button("👥 开始克隆", variant="primary")
                with gr.Column():
                    vc_audio = gr.Audio(label="生成音频")
                    vc_status = gr.HTML("")

        with gr.Tab("自定义音色 (Custom Voice)"):
            gr.Markdown("使用预设说话人，支持愤怒、开心等多种情感控制。")
            with gr.Row():
                with gr.Column():
                    cv_text = gr.Textbox(
                        label="文本",
                        lines=3,
                        placeholder="请输入要合成的文本...",
                    )
                    cv_lang = gr.Dropdown(
                        label="语言", choices=LANGUAGES, value="Auto",
                    )
                    cv_speaker = gr.Dropdown(
                        label="音色", choices=SPEAKERS, value="Vivian",
                    )
                    cv_instruct = gr.Textbox(
                        label="风格",
                        placeholder="例如：用愤怒的语气",
                    )
                    cv_btn = gr.Button("🌟 开始合成", variant="primary")
                with gr.Column():
                    cv_audio = gr.Audio(label="生成音频")
                    cv_status = gr.HTML("")

    error_output = gr.HTML(label="")

    def _submit_tts(service_id, text, mode, language, instruct, speaker, ref_audio, ref_text):
        if not service_id:
            return (
                None, build_status_badge("failed"),
                format_error_message(
                    "请先选择服务",
                    suggestion="在服务管理标签页中配置并启动 TTS 服务",
                ),
            )

        if not text:
            return (
                None, build_status_badge("failed"),
                format_error_message("请输入要合成的文本"),
            )

        ref_audio_b64 = None
        if ref_audio:
            with open(ref_audio, "rb") as f:
                ref_audio_b64 = base64.b64encode(f.read()).decode("utf-8")

        request_payload = {
            "text": text,
            "mode": mode,
            "language": language,
            "instruct": instruct or "",
            "speaker": speaker or "Vivian",
            "ref_audio": ref_audio_b64,
            "ref_text": ref_text or "",
        }

        task_id = scheduler.create_task(
            service_id=service_id,
            model_type="qwen3-tts",
            adapter_name="Qwen3TTSAdapter",
            request_payload={"mode": mode, "text": text[:50]},
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {"mode": mode, "text": text[:100]})

        try:
            adapter = get_adapter("qwen3-tts")
            service = registry.get(service_id)
            service_url = service.service_url if service else ""

            if not service_url:
                raise ValueError("服务 URL 未配置")

            loop = asyncio.new_event_loop()
            task_ref = loop.run_until_complete(
                adapter.submit(service_url=service_url, payload=request_payload)
            )
            loop.close()

            scheduler.update_task_status(task_id, "running")

            for _ in range(60):
                loop = asyncio.new_event_loop()
                status = loop.run_until_complete(
                    adapter.poll_status(service_url, task_ref)
                )
                loop.close()

                if status["status"] in ("completed", "failed"):
                    break
                import time
                time.sleep(2)

            if status["status"] == "completed":
                result_data = status.get("result", {})
                audio_b64 = result_data.get("audio_base64", "")
                sr = result_data.get("sample_rate", 24000)

                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    audio_np = _bytes_to_numpy(audio_bytes)

                    scheduler.update_task_status(
                        task_id, "completed", result_paths=["outputs/tts.wav"]
                    )
                    result_mgr.save_response(task_id, {"mode": mode, "status": "completed"})

                    return (
                        (sr, audio_np),
                        build_status_badge("completed"),
                        "",
                    )

                scheduler.update_task_status(task_id, "completed")
                return (
                    None,
                    build_status_badge("completed"),
                    "生成完成（无音频数据）",
                )

            error_msg = status.get("error", "语音合成失败")
            scheduler.update_task_status(task_id, "failed", error_summary=error_msg)
            return (
                None,
                build_status_badge("failed"),
                format_error_message(
                    error_msg,
                    task_id=task_id,
                    suggestion="请检查 TTS 服务日志或重试",
                ),
            )

        except ConnectionError as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"服务连接失败: {e}"
            )
            return (
                None,
                build_status_badge("failed"),
                format_error_message(
                    "无法连接到 TTS 服务",
                    service_id=service_id,
                    suggestion="请确认服务已启动并且 URL 配置正确",
                    details=str(e),
                ),
            )
        except ValueError as e:
            scheduler.update_task_status(task_id, "failed", error_summary=str(e))
            return (
                None,
                build_status_badge("failed"),
                format_error_message(
                    str(e),
                    service_id=service_id,
                    suggestion="请在服务管理中为该服务设置有效的 service_url",
                ),
            )
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"提交失败: {e}"
            )
            return (
                None,
                build_status_badge("failed"),
                format_error_message(
                    "语音合成请求处理失败",
                    task_id=task_id,
                    suggestion="请查看任务管理标签页获取详细信息",
                    details=str(e),
                ),
            )

    def _bytes_to_numpy(audio_bytes: bytes):
        import wave
        buf = io.BytesIO(audio_bytes)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
        return audio_np

    vd_btn.click(
        fn=lambda s, t, l, i: _submit_tts(s, t, "voice-design", l, i, None, None, None),
        inputs=[service_selector, vd_text, vd_lang, vd_instruct],
        outputs=[vd_audio, vd_status, error_output],
    )

    vc_btn.click(
        fn=lambda s, t, l, ra, rt: _submit_tts(s, t, "voice-clone", l, None, None, ra, rt),
        inputs=[service_selector, vc_text, vc_lang, vc_ref_audio, vc_ref_text],
        outputs=[vc_audio, vc_status, error_output],
    )

    cv_btn.click(
        fn=lambda s, t, l, sp, i: _submit_tts(s, t, "custom-voice", l, i, sp, None, None),
        inputs=[service_selector, cv_text, cv_lang, cv_speaker, cv_instruct],
        outputs=[cv_audio, cv_status, error_output],
    )

    return gr.HTML("")
