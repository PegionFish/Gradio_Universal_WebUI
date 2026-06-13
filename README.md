# Gradio Universal WebUI

基于 Gradio 的统一 AI 前端套件 — 一站式管理本地 AI 负载。支持 Stable Diffusion、Qwen3 ASR、WhisperX、FastWhisper、Waifu2x 五大模型服务。

## 项目状态

**Phase 1-4 全部完成** · 37+ 次提交 · 188+ tests · 100% pass

| Phase | 内容 | 状态 |
|-------|------|------|
| **Phase 1** | 项目骨架 + 10 个模块 + 管理框架 | ✅ 完成 |
| **Phase 2** | Qwen3ASR 真实适配器 + 共享组件库 + 日志流 | ✅ 完成 |
| **Phase 3** | SD/WhisperX/FastWhisper 真实适配器 + 任务重试/取消 + 进度指示器 | ✅ 完成 |
| **Phase 4** | Docker Compose + WebSocket 事件桥 + 认证 + 系统监控 + GPU 智能分配 | ✅ 完成 |

## 快速开始

### 本地运行

```bash
git clone https://github.com/PegionFish/Gradio_Universal_WebUI.git
cd Gradio_Universal_WebUI
pip install -e ".[dev]"
python main.py
```

访问 http://localhost:7860

### Docker 部署

```bash
cp .env.example .env
docker compose up -d                          # 仅启动 WebUI
docker compose --profile full up -d           # 启动全部服务
docker compose --profile gpu up -d            # GPU 服务 + WebUI
```

`docker-compose.yml` 包含 5 个 service：`webui`、`sd-service`、`qwen3-asr`、`whisperx`、`fastwhisper`，通过 `profiles` 按需启动。

### 认证

```bash
python main.py --auth my-secret-token          # CLI 参数
WEBUI_AUTH_TOKEN=my-token python main.py       # 环境变量
# 不设置 = LAN 开放模式
```

每个模型服务支持独立 HTTP API：

| 服务 | 默认端口 | 启动命令 |
|------|---------|---------|
| Stable Diffusion | 17860 | `python services/stable_diffusion_service.py --port 17860` |
| Qwen3 ASR | 8100 | `python services/qwen3_asr_service.py --port 8100 --checkpoint /path/to/model` |
| WhisperX | 8200 | whisperx 库 + `/v1/transcribe` 端点 |
| Waifu2x | 17900 | `python services/waifu2x_service.py --port 17900` |

### 命令行参数

```
python main.py [选项]

选项:
  --host HOST           绑定地址 (默认: 0.0.0.0)
  --port PORT           监听端口 (默认: 7860)
  --config CONFIG       配置目录 (默认: config/)
  --log-level LEVEL     日志级别: DEBUG|INFO|WARNING|ERROR (默认: INFO)
  --auth TOKEN          访问令牌 (空=禁用认证)
```

运行测试：

```bash
pytest          # 188+ tests
```

## 功能概览

### WebUI 标签页（11 个）

| 标签页 | 功能 |
|--------|------|
| **仪表盘** | 服务摘要、最近任务、GPU 概览 |
| **服务管理** | 启动/停止/重启服务、日志查看 + 自动刷新 |
| **任务管理** | 任务筛选、详情查看、重试/取消 |
| **GPU 监控** | GPU 指标卡片、显存推荐排序 |
| **配置** | YAML 编辑器、校验保存、实时生效 |
| **系统健康** | CPU/内存/磁盘使用率、告警阈值 |
| **Stable Diffusion** | txt2img/img2img、完整参数控制、图像画廊 |
| **Qwen3 ASR** | 音频转录、语种选择、SRT 字幕 |
| **WhisperX** | 转录 + 说话人识别 + 词级时间戳 |
| **FastWhisper** | CTranslate2 极速转录 + VAD |
| **Waifu2x** | 图片超分辨率放大（mock 模式） |

#### 配置示例 (`config/services.yaml`)

```yaml
services:
  - id: "sd-webui"
    display_name: "Stable Diffusion"
    model_type: "stable-diffusion"
    enabled: false
    service_url: "http://127.0.0.1:17860"
    health_endpoint: "/health"
    start:
      command: ""
      working_dir: ""
      stop_timeout_seconds: 30
    gpu:
      assignment: [0]
      min_memory_gb: 8

  - id: "qwen3-asr"
    display_name: "Qwen3 ASR"
    model_type: "qwen3-asr"
    enabled: false
    service_url: "http://127.0.0.1:8100"
    health_endpoint: "/health"
```

### 后台服务（守护线程，与 UI 完全解耦）

| 服务 | 功能 |
|------|------|
| HealthChecker | 每 10s HTTP 健康探测 |
| GpuMonitor | 每 5s NVML 指标采集 |
| ProcessManager | 进程生命周期 + 监控 |
| TaskScheduler | SQLite 任务队列 + 重试/取消/统计 |
| SystemMonitor | 每 30s CPU/内存/磁盘采集 |
| EventBuffer | 事件增量轮询 (cursor 模式) |

### GPU 智能分配

- 预留追踪：记录每张 GPU 的显存分配
- 超卖保护：单 GPU 累计预留 ≤ 90%
- 同型号复用：优先分配到已有同类模型的 GPU
- 冲突检测：≥80% warning、≥100% critical

## 项目结构

```
Gradio_Universal_WebUI/
├── main.py                          # CLI 入口
├── pyproject.toml                   # 项目元数据与依赖
├── Dockerfile                       # WebUI 镜像
├── docker-compose.yml               # 5 服务编排
├── .env.example                     # 环境变量模板
├── config/                          # 配置文件
│   └── services.yaml                # 服务定义
├── data/                            # 运行时数据
│   ├── logs/                        # 日志轮转
│   ├── jobs/                        # 任务结果
│   └── tasks.sqlite3                # 任务持久化
├── core/                            # 核心服务 (12 模块)
│   ├── __init__.py                  # setup_core() 统一初始化
│   ├── config_service.py            # YAML 读写/校验/原子写入
│   ├── service_registry.py          # 线程安全服务注册中心
│   ├── event_bus.py                 # 线程安全事件总线
│   ├── process_manager.py           # 进程生命周期管理
│   ├── health_checker.py            # HTTP 健康探测
│   ├── task_scheduler.py            # SQLite 任务队列 + 重试/取消
│   ├── result_manager.py            # 任务结果文件管理
│   ├── gpu_monitor.py               # NVML GPU 指标采集
│   ├── gpu_allocator.py             # GPU 智能分配 + 冲突检测
│   ├── system_monitor.py            # CPU/内存/磁盘监控
│   ├── ws_bridge.py                 # EventBus → 增量轮询桥
│   ├── auth.py                      # 令牌认证管理器
│   ├── logging_setup.py             # 日志初始化 + 轮转
│   └── service_record.py            # 服务记录数据类
├── webui/                           # Gradio UI
│   ├── app.py                       # 应用组装 (11 标签页)
│   ├── state.py                     # 共享状态单例
│   ├── pages/                       # 页面文件
│   │   ├── dashboard.py             # 仪表盘
│   │   ├── services.py              # 服务管理
│   │   ├── tasks.py                 # 任务管理
│   │   ├── gpu.py                   # GPU 监控
│   │   ├── config.py                # 配置编辑器
│   │   ├── system.py                # 系统健康
│   │   ├── login.py                 # 认证登录
│   │   ├── stable_diffusion.py      # SD 模型入口
│   │   ├── qwen3_asr.py             # Qwen3 ASR 模型入口
│   │   ├── whisperx.py              # WhisperX 模型入口
│   │   ├── fastwhisper.py           # FastWhisper 模型入口
│   │   └── waifu2x.py               # Waifu2x 模型入口
│   └── components/                  # 可复用组件
│       ├── service_table.py          # 服务状态表
│       ├── task_list.py              # 任务列表
│       ├── gpu_dashboard.py          # GPU 仪表盘
│       ├── config_editor.py          # 配置编辑器
│       ├── error_display.py          # 错误展示
│       └── progress_indicator.py     # 进度条 + 状态徽章
├── adapters/                        # 模型适配器（全部真实实现）
│   ├── base.py                      # 抽象基类
│   ├── stable_diffusion.py          # SD HTTP 客户端
│   ├── qwen3_asr.py                 # Qwen3ASR HTTP 客户端
│   ├── whisperx.py                  # WhisperX HTTP 客户端
│   ├── fastwhisper.py               # FastWhisper HTTP 客户端
│   └── waifu2x.py                   # Waifu2x HTTP 客户端
├── services/                        # 模型服务包装器
│   ├── qwen3_asr_service.py         # Qwen3ASR HTTP API
│   ├── stable_diffusion_service.py  # SD HTTP API
│   ├── waifu2x_service.py           # Waifu2x HTTP API
│   └── Dockerfile.*                 # 各服务 Dockerfile
├── tests/                           # 测试 (188+ tests, 100% pass)
│   ├── conftest.py                  # 共享 fixtures
│   ├── test_config_service.py
│   ├── test_service_registry.py
│   ├── test_event_bus.py
│   ├── test_process_manager.py
│   ├── test_health_checker.py
│   ├── test_task_scheduler.py
│   ├── test_gpu_monitor.py
│   ├── test_result_manager.py
│   ├── test_adapters.py
│   ├── test_waifu2x*.py
│   ├── test_auth.py
│   └── test_ws_bridge.py
└── docs/                            # 设计文档
    └── superpowers/specs/           # 10 个模块实现规格
```

## 技术栈

- **前端**: Gradio 6.x (Python WebUI 框架)
- **配置**: PyYAML + 原子写入 (.tmp + rename)
- **监控**: NVML (nvidia-ml-py) + psutil
- **持久化**: SQLite (WAL 模式) + 文件系统
- **异步**: aiohttp + asyncio 事件循环
- **容器化**: Docker + Compose (5 服务编排)
- **测试**: pytest + pytest-asyncio (188+ tests)
- **认证**: 令牌会话 + url-safe session ID

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `WEBUI_PORT` | 7860 | WebUI 端口 |
| `WEBUI_AUTH_TOKEN` | (空) | 设置后启用 LAN 认证 |
| `SD_PORT` | 17860 | SD 服务端口 |
| `SD_BACKEND` | diffusers | SD 后端 (diffusers/openai/automatic1111) |
| `QWEN3_PORT` | 8100 | Qwen3 ASR 端口 |
| `WHISPERX_PORT` | 8200 | WhisperX 端口 |
| `FW_PORT` | 8300 | FastWhisper 端口 |

## 开发

```bash
pip install -e ".[dev]"
pytest                          # 177 tests
python main.py --log-level DEBUG
```

提交规范（细粒度）：每个 commit 只做一件事，前缀标注领域：

```
[组件] / [适配器] / [服务] / [页面] / [日志] / [调度器] / 
[GPU] / [系统] / [认证] / [实时] / [部署] / [测试]
```

## 许可证

AGPL-3.0-only
