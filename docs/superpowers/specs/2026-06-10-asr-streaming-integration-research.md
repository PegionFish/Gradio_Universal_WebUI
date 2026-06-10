# Qwen3-ASR-Stream-Docker 集成研究记录

日期: 2026-06-10
状态: 研究完成，等待讨论后决策

## 背景

对 `E:\Qwen3-ASR-Stream-Docker\Qwen3-ASR-Stream-Docker\` 项目进行了完整源码分析，
评估其与 Gradio Universal WebUI 的集成方案。

## 外部项目分析

### Qwen3-ASR-Stream-Docker 结构

```
Qwen3-ASR-Stream-Docker/
├── docker-compose.yml          # 单服务编排，端口 8000，GPU reservation
├── dockerImages.tar            # 18GB Docker 镜像 (qwen3_asr_stream:dsx001)
└── data/
    ├── demo_streaming.py        # Flask 应用，流式转录 HTTP API + HTML 前端
    └── example_qwen3_asr_vllm_streaming.py  # Python SDK 用法示例
```

### 流式 ASR HTTP 协议

与批处理 `/v1/transcribe` 完全不同，采用**会话式 chunk 协议**：

| 端点 | 请求 | 响应 |
|------|------|------|
| `POST /api/start` | 空 | `{"session_id": "hex-string"}` |
| `POST /api/chunk?session_id=X` | `Content-Type: application/octet-stream`，float32 16kHz mono raw bytes (每 500ms 一段 = 8000 samples) | `{"language": "zh", "text": "增量累积文本"}` |
| `POST /api/finish?session_id=X` | 空 | `{"language": "zh", "text": "最终完整文本"}` |

- 会话 TTL: 10 分钟
- 无时间戳，无 segments，无 SRT 输出
- 前端 HTML 使用 `getUserMedia` 捕获物理麦克风

### Python SDK 用法

```python
from qwen_asr import Qwen3ASRModel

asr = Qwen3ASRModel.LLM(
    model="Qwen/Qwen3-ASR-1.7B",
    gpu_memory_utilization=0.8,
    max_model_len=8192,
    max_new_tokens=32,
)

state = asr.init_streaming_state(
    unfixed_chunk_num=4, unfixed_token_num=5, chunk_size_sec=1.0,
)
asr.streaming_transcribe(wav_chunk_16k, state)   # 每次喂一个 chunk
asr.finish_streaming_transcribe(state)           # 收尾
# state.language, state.text                      # 读取结果
```

## 现有 WebUI ASR 基础设施

当前 WebUI 有三条 ASR 路径：

| 路径 | 组件 | 协议 | 能力 |
|------|------|------|------|
| **Qwen3 批处理** | `adapters/qwen3_asr.py` + `services/qwen3_asr_service.py` + `webui/pages/qwen3_asr.py` | `POST /v1/transcribe` → `GET /v1/status/<id>` | 上传文件→等待→文本 |
| **Qwen3 流式** | `adapters/qwen3_streaming.py` (刚提交) + Docker 服务 | 会话式 chunk | 实时增量文本，无时间戳 |
| **WhisperX** | `adapters/whisperx.py` + `webui/pages/whisperx.py` | `POST /v1/transcribe` → 状态轮询 | 词级时间戳 + SRT + diarization |

## 能力对比矩阵

| 能力 | Qwen3 批处理 (8100) | Qwen3 流式 (8000) | WhisperX (8200) |
|------|---------------------|--------------------|--------------------|
| 实时增量文本 | ❌ | ✅ 每 500ms | ❌ |
| 词级时间戳 | ❌ | ❌ | ✅ |
| SRT 字幕输出 | ❌ | ❌ | ✅ 可直接生成 |
| 说话人识别 | ❌ | ❌ | ✅ diarization |
| 音频流捕获 | ❌ 需录音→上传 | ✅ 浏览器麦克风 | ❌ 需录音→上传 |
| 文件上传转录 | ✅ | ✅ 模拟流式 | ✅ |
| 延迟 | 秒级 | 毫秒级 | 秒级 |
| 部署方式 | Python SDK 直接加载 | Docker 镜像 (vLLM) | Python 库直接加载 |

## 初步结论

### 建议简化：三条线 → 两条线

**Qwen3 批处理和流式能力重叠**——流式可以覆盖批处理的所有场景（上传完整音频→分块发送模拟流式）。两者只需要留一个。

**WhisperX 是字幕文件的唯一来源**——需要时间戳 + SRT + 说话人识别时只能用 WhisperX。

| 保留 | 用途 | 输出 |
|------|------|------|
| Qwen3 流式 | 实时转录 / 音频流捕获 | 增量文本 |
| WhisperX | 离线精准转录 + 字幕文件 | 全文 + segments + SRT |

### 待讨论的开放问题

1. **Qwen3 流式 Docker 依赖**：镜像 `qwen3_asr_stream:dsx001` 约 18GB，使用 vLLM 后端。如果未来需要纯 Python 部署（不用 Docker），流式版需要额外适配——Qwen3 批处理可直接用 `qwen_asr` SDK 本地加载，而流式版嵌在镜像里。

2. **是否需要移除批处理**：`qwen3_asr_service.py` + `adapters/qwen3_asr.py` 批处理部分已提交为功能代码，是否正式标记为 deprecated 或直接删除取决于后续部署策略。

3. **文件上传→SRT 的流程**：WhisperX 负责精准转录 + 字幕，Qwen3 流式负责实时交互——这个分工还需要在 WebUI 页面上体现为两个明确的标签页入口。

4. **音频流路由方案**（场景 2：捕获本机播放的音频）：
   - Windows: Stereo Mix 或 VB-Cable 虚拟声卡
   - Mac: BlackHole
   - Linux: pipewire/pulseaudio 原生路由
   这些都是 OS 层面配置，不是 WebUI 能自动处理的。

### 后续步骤

- 决策三条 ASR 线保留/删除方案
- 若保留 Qwen3 流式，设计 WebUI 页面（麦克风实时 + 文件流式上传两种模式）
- 若删除 Qwen3 批处理，清理相关代码和 Docker 编排
- 统一 WhisperX 和 Qwen3 流式的 WebUI 入口体验
