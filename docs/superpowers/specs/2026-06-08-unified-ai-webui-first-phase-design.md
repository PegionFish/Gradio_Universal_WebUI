---
name: unified-ai-webui-first-phase-design
description: 基于 Gradio 的统一 AI 前端套件第一阶段设计，管理本地 AI 负载
metadata:
  type: project
---

# 统一 AI WebUI 第一阶段设计

日期: 2026-06-08

## 1. 目标

构建基于 Gradio 的统一 AI 前端套件第一阶段，面向 Linux 本地服务器上为局域网用户提供服务。该套件提供一个对外 WebUI 端口，集中管理导航、控制、配置、任务调度、服务管理和 GPU 监控，同时每个 AI 模型服务作为独立 HTTP 服务保留自己的端口。

第一阶段实现框架和管理层。Qwen3ASR、WhisperX 和 FastWhisper 的模型推理功能推迟到后续阶段实现。Stable Diffusion、Qwen3ASR、WhisperX 和 FastWhisper 在第一阶段以可插拔的模型入口和适配器占位形式存在。

Brainstorm 阶段收集的参考材料:
- Qwen3ASR: 开发机上的 `E:\Qwen3ASR\qwen-asr-1.7B\app.py` —— 一个独立的 Gradio demo，使用 Transformers/vLLM 后端，支持音频上传、时间戳强制对齐器和 SRT 字幕输出。第一阶段不集成此项目，但作为后续适配器实现的主要参考。

## 2. 已确认需求

- 单个 Gradio WebUI 通过一个对外端口暴露所有管理功能
- 每个模型服务保留自己的 HTTP 端口，供其他应用直接调用或搭建自动化工作流
- 第一阶段局域网用户无需认证即可访问全部功能
- 必须支持 NVIDIA GPU 加速
- 用户能以最高粒度选择目标 GPU
- 系统展示 GPU 显存、利用率、温度和工作负载状态
- 系统根据当前负载推荐合适的 GPU，但用户保留最终决定权
- 模型服务可部署在不同 GPU 上，或多个模型共享同一 GPU，取决于配置和工作负载
- 通过 WebUI 管理配置，实时保存到本地 YAML 文档
- 任务队列和任务历史通过 SQLite 持久化
- 任务结果文件存储在项目固定目录 `data/jobs/`
- WebUI 能启动、停止、重启和监控模型服务
- 第一阶段目标部署环境为 Linux 本地服务器，面向局域网用户
- Python 环境管理在第一阶段不做锁定，设计保留 venv、conda、容器化等扩展点

## 3. 范围

### 第一阶段纳入范围

- 单个公共端口的 Gradio 统一 WebUI
- 以下模型的导航和入口页面:
  - Stable Diffusion
  - Qwen3ASR
  - WhisperX
  - FastWhisper
- 服务注册表和服务配置，存储在 YAML 中
- WebUI 配置编辑器，持久化到 YAML
- 服务管理器：启动、停止、重启和状态显示
- HTTP 模型服务的健康检查
- SQLite 支撑的任务队列和任务历史
- `data/jobs/` 下的结果文件管理
- NVIDIA GPU 监控和建议逻辑
- 模型服务的适配器接口定义
- 首批模型条目的占位适配器
- 基础错误处理、日志和面向用户的状态消息
- 不涉及模型推理的核心框架测试

### 第一阶段不纳入范围

- 认证、授权和多用户权限管理
- Qwen3ASR 完整推理集成
- WhisperX 完整推理集成
- FastWhisper 完整推理集成
- 将 Stable Diffusion 绑定到特定后端（如 A1111、ComfyUI 或 Diffusers）
- 自动 GPU 保护（阻止用户提交作业）
- 以 Docker Compose 为主要部署方式
- 多用户角色分离
- 跨多模型服务的长时间工作流编排
- 生产级远程部署加固

## 4. 系统架构

```text
局域网浏览器
   |
   v
[ 统一 Gradio WebUI : 一个对外端口 ]
   |
   |-- 导航与模型页面
   |-- 控制面板
   |-- 配置编辑器
   |-- 任务队列界面
   |-- GPU 监控
   |-- 服务管理器
   |
   v
[ WebUI 进程内部的核心服务 ]
   |-- ConfigService       配置服务
   |-- ServiceRegistry     服务注册中心
   |-- ProcessManager      进程管理器
   |-- HealthChecker       健康检查器
   |-- TaskScheduler       任务调度器
   |-- GpuMonitor          GPU 监控器
   |-- ResultManager       结果管理器
   |
   v
[ 适配器层 ]
   |-- BaseModelAdapter
   |-- StableDiffusionAdapter 占位
   |-- Qwen3ASRAdapter        占位
   |-- WhisperXAdapter        占位
   |-- FastWhisperAdapter     占位
   |
   v
[ 独立模型 HTTP 服务 ]
   |-- stable-diffusion-service : 自有 HTTP 端口
   |-- qwen3-asr-service : 后续
   |-- whisperx-service : 后续
   |-- fastwhisper-service : 后续
```

## 5. 参考项目分析

以下分析基于 `E:/` 盘中已有的 AI 项目，提取出对统一 WebUI 架构有参考价值的模式。

### 5.1 sd-webui-aki（E:\sd-webui-aki\）

启动入口: `launch.py` → `webui.py` 两级结构。`launch.py` 处理环境准备（依赖检查、git 子模块），`webui.py` 完成应用启动。

**可参考的模式：**

- **模块化 CLI 参数** (`modules/cmd_args.py`)：所有 CLI 参数集中在单个文件中定义，使用 `argparse`，包括 `--device-id`、`--medvram`、`--api`、`--port` 等，被各模块引用。
- **设备管理** (`modules/devices.py`)：集中的 GPU 设备管理，通过 `--device-id` 控制 CUDA 设备选择，支持 `cuda`、`mps`、`xpu`、`cpu` 的自动回退。
- **UI 工厂模式** (`modules/ui.py`)：每个标签页（txt2img、img2img 等）各自构建独立的 `gr.Blocks` 实例，收集到 `interfaces` 列表，再由主程序用 `gr.Tabs()` 统一渲染。扩展通过 `script_callbacks.ui_tabs_callback()` 注册。
- **回调注册系统** (`modules/script_callbacks.py`)：通过全局回调列表实现组件间通信。`ui_tabs_callback`、`ui_settings_callback`、`before_reload_callback` 等回调点让扩展和核心模块可以互相通知。
- **GRADIO_ANALYTICS_ENABLED=False** 环境变量禁用 Gradio 遥测。

### 5.2 FireRed-OCR（E:\FireRed-OCR\）

**可参考的模式：**

- **多标签页共享状态**：使用 `gr.Tabs()` 内嵌 3 个标签页（单张/多张/PDF），所有标签页共享同一组 `outputs`（6 个输出组件：状态、日志、结果、下载文件、模型状态、运行时信息），生成器函数 `yield` 更新全部输出。
- **延迟加载+线程安全**：模型使用 `threading.Lock()` 保护的单例延迟加载模式，首次调用时才加载，避免启动耗时。
- **离线强制模式**：通过自定义 `OfflineBlockedSocket` 类在 socket 级别阻止非 localhost 连接，配合 `HF_HUB_OFFLINE=1` 等环境变量实现完全离线。

### 5.3 Qwen3ASR（E:\Qwen3ASR\）

**可参考的模式：**

- **build_parser() 模式**：所有 CLI 参数集中定义，生成清晰的帮助文档。`--asr-checkpoint`、`--backend`、`--cuda-visible-devices`、以 JSON 字符串传入的 `--backend-kwargs` 和 `--aligner-kwargs`。
- **GPU 分配**：通过 `_apply_cuda_visible_devices()` 函数在进程启动时设置 `CUDA_VISIBLE_DEVICES` 环境变量，后续模型加载自然遵循该限制。
- **通过 JSON 字符串实现灵活配置**：`--backend-kwargs '{"device_map":"cuda:0","dtype":"bfloat16"}'` 模式，在保持 CLI 接口稳定的同时提供高度灵活性。
- **Gradio 完整配置**：`server_name`、`server_port`、`share`、`ssl_certfile`、`ssl_keyfile`、`ssl_verify`、`concurrency` 全部作为 CLI 参数暴露。

### 5.4 whisperx-offline / faster-whisper-offline

**可参考的模式：**

- **嵌入式 Python 分发**：整套 Python 运行时 + CUDA DLL + 模型文件打包在项目目录内，无需用户安装 Python 或 CUDA。`start.bat` 用 `os.add_dll_directory()` 加载 CUDA DLL。
- **纯离线运行**：模型文件预先下载到本地 `models/` 目录，不依赖 HuggingFace 在线访问。
- 架构上较为简单（单文件 Gradio 应用），对本项目的模块化设计参考价值有限。

### 5.5 模式总结

| 模式 | 来源 | 应用到本项目 |
|------|------|-------------|
| `modules/cmd_args.py` 统一 CLI 参数 | sd-webui | `core/cli_args.py` 集中定义 CLI 参数 |
| GPU 设备管理器 | sd-webui | `core/gpu_monitor.py` 扩展为监控+分配 |
| 回调注册/事件系统 | sd-webui | Core Service 间通过 EventBus 通信 |
| 多标签页共享输出 | FireRed-OCR | WebUI 共享 `gr.State` 跨标签页同步 |
| 延迟加载+线程安全 | FireRed-OCR | ProcessManager 的 lazy start |
| `build_parser()` 模式 | Qwen3ASR | `main.py` 的 CLI 入口 |
| JSON kwargs 灵活配置 | Qwen3ASR | 适配器参数通过 JSON 字符串传递 |
| CUDA_VISIBLE_DEVICES 分配 GPU | Qwen3ASR | ProcessManager 的 GPU 分配策略 |

## 6. 项目目录结构

```text
Gradio_Universal_WebUI/
├── main.py                        # CLI 入口
├── pyproject.toml                 # 项目元数据和依赖
├── config/
│   ├── services.yaml              # 模型服务定义
│   └── webui.yaml                 # WebUI 服务器设置（端口、主机、刷新间隔）
├── data/
│   ├── tasks.sqlite3              # SQLite 任务队列和历史
│   └── jobs/                      # 任务结果文件
│       └── <task_id>/
│           ├── request.json
│           ├── response.json
│           ├── logs/
│           └── outputs/
├── webui/
│   ├── __init__.py
│   ├── app.py                     # Gradio Blocks 应用组装
│   ├── pages/                     # 每个 Gradio 标签页一个文件
│   │   ├── __init__.py
│   │   ├── dashboard.py           # 概览/首页
│   │   ├── services.py            # 服务管理页面
│   │   ├── tasks.py               # 任务队列和历史页面
│   │   ├── gpu.py                 # GPU 监控页面
│   │   ├── config.py              # 配置编辑器页面
│   │   ├── stable_diffusion.py    # 模型入口页面（占位）
│   │   ├── qwen3_asr.py           # 模型入口页面（占位）
│   │   ├── whisperx.py            # 模型入口页面（占位）
│   │   └── fastwhisper.py         # 模型入口页面（占位）
│   ├── components/                # 可复用 Gradio 组件
│   │   ├── __init__.py
│   │   ├── service_table.py
│   │   ├── task_list.py
│   │   ├── gpu_dashboard.py
│   │   ├── config_editor.py
│   │   └── error_display.py
│   └── state.py                   # 共享响应式状态 (gr.State)
├── core/
│   ├── __init__.py
│   ├── config_service.py          # YAML 读写/校验
│   ├── service_registry.py        # 服务元数据存储
│   ├── process_manager.py         # 启动/停止/重启服务
│   ├── health_checker.py          # 定时 HTTP 健康探测
│   ├── task_scheduler.py          # SQLite 支撑的任务队列
│   ├── gpu_monitor.py             # 基于 NVML 的 GPU 指标
│   └── result_manager.py          # data/jobs/ 文件管理
├── adapters/
│   ├── __init__.py
│   ├── base.py                    # 抽象基类适配器
│   ├── stable_diffusion.py        # 占位适配器
│   ├── qwen3_asr.py               # 占位适配器
│   ├── whisperx.py                # 占位适配器
│   └── fastwhisper.py             # 占位适配器
├── tests/
│   ├── __init__.py
│   ├── test_config_service.py
│   ├── test_service_registry.py
│   ├── test_process_manager.py
│   ├── test_health_checker.py
│   ├── test_task_scheduler.py
│   ├── test_gpu_monitor.py
│   ├── test_result_manager.py
│   └── test_adapters.py
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-06-08-unified-ai-webui-first-phase-design.md
```

## 7. 组件设计

### 7.1 Gradio WebUI

WebUI 是唯一对外暴露的用户界面。

#### 页面结构

WebUI 使用 Gradio `gr.Blocks` 配合 `gr.Tabs` 实现顶层导航：

| 标签页 | 页面文件 | 用途 |
|--------|---------|------|
| 仪表盘 | `dashboard.py` | 首页：服务摘要、最近任务、GPU 概览 |
| 服务管理 | `services.py` | 服务状态表、启动/停止/重启控制、日志查看 |
| 任务管理 | `tasks.py` | 任务提交、队列状态、任务历史、结果链接 |
| GPU 监控 | `gpu.py` | 每个 GPU 的指标仪表盘和推荐面板 |
| 配置 | `config.py` | YAML 编辑器、服务定义增删改、校验反馈 |
| Stable Diffusion | `stable_diffusion.py` | 模型入口页面（占位） |
| Qwen3 ASR | `qwen3_asr.py` | 模型入口页面（占位） |
| WhisperX | `whisperx.py` | 模型入口页面（占位） |
| FastWhisper | `fastwhisper.py` | 模型入口页面（占位） |

每个模型入口页面提供：
- 服务选择下拉框（若同类型有多个服务）
- 目标 GPU 选择器，附推荐指标
- 模型专属参数占位区域（标注"预留供后续实现"）
- 提交按钮，通过适配器层路由并展示任务结果
- 跳转到任务管理标签页查看完整历史

占位页面显示清晰提示：
> "此模型适配器已为未来阶段预留。请在服务管理标签页中配置服务，等适配器实现后再来使用。"

#### app.py 组装逻辑

`webui/app.py` 采用类似 sd-webui-aki 的 UI 工厂模式 + FireRed-OCR 的共享输出模式。每个页面文件导出两个函数：

```python
# 每个 pages/*.py 的约定接口:
def create_page() -> gr.Blocks:
    """返回该标签页的 gr.Blocks 实例。"""
    ...

def get_shared_state() -> list[gr.State]:
    """返回该标签页依赖的共享 State 列表。"""
    ...
```

`app.py` 负责收集所有页面并组装到主 Blocks 中：

```python
# webui/app.py —— 应用组装
import gradio as gr
from webui import pages
from webui.state import AppState  # 单例 AppState 持有 gr.State 创建

def create_app() -> gr.Blocks:
    state = AppState()  # 在 Blocks 外部创建 State（跨页面共享）
    
    with gr.Blocks(theme=gr.themes.Soft(), title="统一 AI WebUI", css=CSS) as app:
        gr.Markdown("# 统一 AI WebUI")
        
        with gr.Tabs(elem_id="main-tabs"):
            # 主功能标签页（按定义顺序渲染）
            for page_fn in [
                pages.dashboard.create_page,
                pages.services.create_page,
                pages.tasks.create_page,
                pages.gpu.create_page,
                pages.config.create_page,
            ]:
                page = page_fn()
                page.render()
            
            # 模型入口标签页（占位，无推理能力）
            for model_page_fn in [
                pages.stable_diffusion.create_page,
                pages.qwen3_asr.create_page,
                pages.whisperx.create_page,
                pages.fastwhisper.create_page,
            ]:
                page = model_page_fn()
                page.render()
    
    return app


def launch_app(app: gr.Blocks, host: str, port: int):
    app.queue(default_concurrency_limit=16).launch(
        server_name=host,
        server_port=port,
        share=False,
        show_error=True,
    )
```

说明：

- 此模式参考 sd-webui-aki 的 `modules/ui.py` 将所有独立 `gr.Blocks` 实例收集到列表统一渲染。
- `gr.State` 通过 `AppState` 单例在 `gr.Blocks` 上下文之外创建，确保跨标签页共享同一引用。
- 模型入口页面文件导出与主功能标签页相同的接口，方便后续阶段从占位切换为完整实现。

#### 启动序列

`main.py` 是 CLI 入口点，按以下顺序启动：

```text
main.py 启动序列：

1. 解析 CLI 参数 (argparse)
   │   --host, --port, --config, --log-level 覆盖 config/webui.yaml
   │
2. 初始化日志系统
   │   根据 config/webui.yaml logging 配置，设置 RotatingFileHandler
   │
3. 加载配置 (ConfigService)
   │   ├── 若 config/webui.yaml 不存在 → 创建默认配置
   │   ├── 若 config/services.yaml 不存在 → 创建含四个占位服务的默认配置
   │   └── 校验失败 → 打印错误并退出
   │
4. 初始化 ServiceRegistry
   │   从加载的 YAML 构建服务记录字典
   │
5. 启动后台线程
   │   ├── HealthChecker 线程 (daemon=True)
   │   ├── GpuMonitor 线程 (daemon=True)
   │   └── ProcessManager 监控线程 (daemon=True)
   │
6. Auto-start 启用的服务
   │   对 enabled=true 且 start.command 非空的服务:
   │   ├── ProcessManager.start(service_id)
   │   └── HealthChecker 开始探测
   │
7. 构建并启动 WebUI
   │   ├── webui/app.py → create_app()
   │   ├── demo.queue().launch()
   │   └── 阻塞，直到用户 Ctrl+C
   │
8. 关闭
   │   ├── 停止所有后台线程
   │   ├── 停止所有运行中的服务 (SIGTERM → 超时 → SIGKILL)
   │   └── 退出
```

此启动序列确保在打开 WebUI 端口之前，所有核心服务和自动启用的模型服务已经就绪。后台线程均为 `daemon=True`，主进程退出时自动终止。

#### 核心服务生命周期

核心服务（ConfigService、ServiceRegistry、ProcessManager、HealthChecker、TaskScheduler、GpuMonitor、ResultManager）作为 Python 模块级单例存在，不通过依赖注入容器管理。各服务的引用方式为：

```python
# core/__init__.py
from core.config_service import ConfigService
from core.service_registry import ServiceRegistry
from core.process_manager import ProcessManager
from core.health_checker import HealthChecker
from core.task_scheduler import TaskScheduler
from core.gpu_monitor import GpuMonitor
from core.result_manager import ResultManager

config = ConfigService()
registry = ServiceRegistry()
process_manager = ProcessManager()
health_checker = HealthChecker()
scheduler = TaskScheduler()
gpu_monitor = GpuMonitor()
result_mgr = ResultManager()
```

各页面通过 `from core import registry, scheduler` 等直接引用所需服务。这种模式参考了 sd-webui-aki 的 `modules/` 包结构，核心模块通过 `import` 链自动初始化，页面文件按需引用。

#### 启动后刷新流程

```text
                     ┌─────────────────────────────┐
                     │  gr.Blocks.launch() 阻塞运行  │
                     └─────────────────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
         ▼                        ▼                        ▼
  HealthChecker 线程        GpuMonitor 线程          ProcessManager 监控线程
  ┌────────────────┐    ┌─────────────────┐    ┌────────────────────────┐
  │ 每10秒:         │    │ 每5秒:           │    │ 每15秒:                 │
  │ for 每个服务:   │    │ NVML 采集指标    │    │ for 每个已启动服务:     │
  │   健康端点探测  │    │ 更新 GpuSnapshot │    │   process.poll() 检查  │
  │   更新服务状态  │    │ 计算推荐排序      │    │   若已退出 → 标记状态   │
  └────────────────┘    └─────────────────┘    └────────────────────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  │
                                  ▼
                         UI 读取共享状态
                         ┌──────────────────┐
                         │ gr.State 或       │
                         │ 回调读取最新数据   │
                         └──────────────────┘
```

#### 共享状态

WebUI 通过 `gr.State` 维护共享响应式状态：
- `enabled_services` —— 已配置的服务列表
- `service_statuses` —— 每个服务的运行/停止/不健康状态
- `gpu_metrics` —— 最新 GPU 快照
- `refresh_counter` —— 驱动周期性界面更新

#### 刷新策略

Gradio `gr.Blocks` 不自带自动刷新功能，采用以下方案保持界面更新：

- **仪表盘和服务管理标签页**：使用 `gr.HTML` 配合 `<meta http-equiv="refresh">`，或通过隐藏周期性回调更新 `gr.Number` 触发 `.change()` 事件。
- **GPU 监控**：每 5 秒通过定时回调刷新。
- **健康状态**：HealthChecker 在后台线程每 10 秒运行一次；UI 在用户交互或切换标签页时读取共享状态。
- **任务状态**：任务管理标签页激活时轮询（手动刷新按钮 + 存在运行中任务时自动每 15 秒轮询）。

WebUI 不直接实现模型推理，将所有模型工作委托给适配器和 HTTP 模型服务。

### 7.2 ConfigService（配置服务）

`ConfigService` 负责 YAML 配置的读写。WebUI 通过表单和表格编辑配置，实时持久化到磁盘。

#### 配置文件

| 文件 | 用途 |
|------|------|
| `config/webui.yaml` | WebUI 服务器设置（端口、主机、刷新间隔） |
| `config/services.yaml` | 模型服务定义 |

#### `config/webui.yaml` 结构

```yaml
server:
  host: "0.0.0.0"
  port: 7860
  public_url: ""              # 可选的公网/外部 URL 覆盖

refresh:
  health_check_seconds: 10
  gpu_metrics_seconds: 5
  task_status_seconds: 15

logging:
  level: "INFO"               # DEBUG, INFO, WARNING, ERROR
  max_mb_per_file: 10
  backup_count: 5
  directory: "data/logs/"
```

#### `config/services.yaml` 结构

```yaml
services:
  - id: "sd-webui"                  # 稳定服务 ID
    display_name: "Stable Diffusion"
    model_type: "stable-diffusion"  # 映射到适配器
    enabled: true                    # WebUI 启动时自动启动
    service_url: "http://127.0.0.1:17860"   # 若已在外部运行
    health_endpoint: "/health"
    start:
      command: "python serve.py"    # 相对于 working_dir，或使用绝对路径
      working_dir: "/opt/stable-diffusion"
      env:
        CUDA_VISIBLE_DEVICES: "0"
        HF_HOME: "/data/huggingface"
      stop_timeout_seconds: 30      # 优雅关闭等待时间，超时后 SIGKILL
    gpu:
      assignment: [0]               # 允许的 GPU 索引；空数组表示不限制
      min_memory_gb: 8              # 该服务所需的最小 VRAM

  - id: "qwen3-asr"
    display_name: "Qwen3 ASR"
    model_type: "qwen3-asr"
    enabled: false
    service_url: ""
    health_endpoint: "/health"
    start:
      command: ""
      working_dir: ""
      env: {}
      stop_timeout_seconds: 30
    gpu:
      assignment: []
      min_memory_gb: 0

  # WhisperX 和 FastWhisper 使用相同结构
```

如果 `start.command` 为空但 `service_url` 已设置，WebUI 将该服务视为外部托管（不提供启动/停止控制，仅进行健康检查）。

#### 校验规则

- `id`: 小写字母数字加连字符，在所有服务中唯一
- `display_name`: 非空
- `model_type`: 必须为 `stable-diffusion`、`qwen3-asr`、`whisperx`、`fastwhisper` 之一（后续阶段可扩展）
- `service_url`: 合法的 HTTP/HTTPS URL
- `start.command`: 若非空，则 `working_dir` 也必须非空
- `gpu.assignment`: 每个索引必须为非负整数
- `gpu.min_memory_gb`: 非负整数
- `stop_timeout_seconds`: 介于 5 到 120 之间

WebUI 在保存前必须校验配置。校验失败必须以字段级错误信息拒绝保存，不得覆盖先前有效的文件。保存操作采用"先写临时文件再重命名"的模式，防止写入不完整。

### 7.3 ServiceRegistry（服务注册中心）

`ServiceRegistry` 以线程安全的内存字典存储所有已知模型服务。启动时从 YAML 加载，可以在不重启 WebUI 的情况下重新加载。

每个服务记录包含：

- `id`: 稳定服务 ID
- `display_name`: 人类可读的服务名
- `model_type`: 映射到适配器类
- `enabled`: 是否在 WebUI 启动时自动启动
- `service_url`: API 调用的 HTTP URL
- `service_url_internal`: 预留用于 Docker 桥接网络场景
- `health_endpoint`: 健康探测路径
- `start_command`、`working_dir`: 进程启动参数
- `env`: 环境变量覆盖
- `stop_timeout_seconds`: 优雅关闭超时
- `gpu_assignment`: 允许的 GPU 索引
- `gpu_min_memory_gb`: 最小 VRAM 需求
- `runtime_state`: 取值为 `stopped`、`starting`、`running`、`unhealthy`、`stopping`、`exited`
- `pid`: 进程 ID，非托管则为 None

ServiceRegistry 使用 `threading.Lock` 保护所有读写操作。**所有对 `runtime_state` 的修改必须通过 `set_runtime_state()` 方法**，该方法在加锁更新状态后发布事件。

### 7.4 EventBus（事件系统）

参考 sd-webui-aki 的 `script_callbacks.py` 回调注册模式，实现一个简单的同步事件总线，用于核心服务之间的松耦合通信。

#### EventBus 接口

```python
# core/event_bus.py
from dataclasses import dataclass, field
from typing import Callable, Any
import threading

@dataclass
class Event:
    type: str                     # 事件类型，如 "service_state_changed"
    data: dict[str, Any]          # 事件负载
    source: str = ""              # 事件来源标识

class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: dict[str, list[Callable]] = {}
    
    def on(self, event_type: str, handler: Callable):
        """注册事件处理器。handler(Event) -> None"""
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)
    
    def off(self, event_type: str, handler: Callable):
        """移除事件处理器。"""
        with self._lock:
            self._handlers.get(event_type, []).remove(handler)
    
    def emit(self, event: Event):
        """发布事件，同步调用所有已注册的处理器。"""
        handlers = list(self._handlers.get(event.type, []))
        for handler in handlers:
            handler(event)


# 全局单例
bus = EventBus()
```

#### 事件类型

| 事件 | 负载 | 发布者 | 消费者 |
|------|------|--------|--------|
| `service_state_changed` | `{"service_id": ..., "old_state": ..., "new_state": ...}` | ServiceRegistry | HealthChecker, GpuMonitor, WebUI |
| `config_reloaded` | `{"service_ids": [...]}` | ConfigService | ServiceRegistry, ProcessManager |
| `service_added` | `{"service_id": ..., "model_type": ...}` | ServiceRegistry | WebUI |
| `service_removed` | `{"service_id": ...}` | ServiceRegistry | ProcessManager, WebUI |
| `gpu_metrics_updated` | `{"gpus": [...]}` | GpuMonitor | WebUI |
| `task_completed` | `{"task_id": ..., "service_id": ..., "status": ...}` | TaskScheduler | WebUI |

#### 使用示例

```python
# core/service_registry.py
from core.event_bus import bus, Event

class ServiceRegistry:
    def set_runtime_state(self, service_id: str, new_state: str):
        with self._lock:
            record = self._services.get(service_id)
            if not record:
                return
            old_state = record.runtime_state
            record.runtime_state = new_state
        
        # 在锁外发布事件，避免死锁
        bus.emit(Event(
            type="service_state_changed",
            data={"service_id": service_id, "old_state": old_state, "new_state": new_state},
            source="ServiceRegistry",
        ))


# core/health_checker.py - 订阅状态变化
from core.event_bus import bus

def _on_service_state_changed(event: Event):
    data = event.data
    if data["new_state"] == "running":
        # 服务刚变为运行状态 → 开始健康探测
        pass
    elif data["new_state"] in ("stopped", "exited"):
        # 服务已停止 → 停止健康探测
        pass

bus.on("service_state_changed", _on_service_state_changed)
```

#### 线程模型

整个系统使用 **同步多线程模型**。所有核心服务运行在 `threading.Thread` 守护线程中。

| 线程 | 用途 | 守护线程 |
|------|------|---------|
| 主线程 | Gradio `launch()` 阻塞运行 | — |
| HealthChecker | 每 10 秒探测服务健康状态 | 是 |
| GpuMonitor | 每 5 秒采集 GPU 指标 | 是 |
| ProcessManager watcher | 每 15 秒检查进程存活 | 是 |
| TaskScheduler (可选) | 若需要后台轮询服务的任务状态 | 是 |
| Gradio 回调线程 | 用户交互触发的回调（Gradio 内部管理） | 是 |

**关键规则：**

- **Gradio 回调函数**（用户点击按钮触发的 Python 函数）运行在 Gradio 内部线程池中，不能阻塞超过 30 秒。长时间操作（如启动模型服务）应在守护线程中执行，回调仅触发并返回中间状态。
- **共享数据访问**：所有跨线程的共享状态通过 `threading.Lock` 保护。`gr.State` 中的数据只有 Gradio 回调线程写入/读取，后台线程**不直接修改** `gr.State`。
- **后台线程 → UI 更新路径**：后台线程写入模块级变量（如 ServiceRegistry 的状态、GpuSnapshot），UI 通过 Gradio 回调（`gr.Timer` 事件或用户点击）主动拉取最新数据。

#### Gradio 5.x 定时刷新

使用 `gr.Timer` 替代"隐藏 `gr.Number` + `.change()`"模式：

```python
# pages/dashboard.py 示例
import gradio as gr
from core import registry, gpu_monitor

def create_page() -> gr.Blocks:
    with gr.Blocks() as page:
        timer = gr.Timer(value=5)  # 每 5 秒触发
        status_html = gr.HTML("加载中...")
        
        def refresh():
            services = registry.list_services()
            html = _build_service_summary_html(services)
            return gr.update(value=html)
        
        timer.tick(refresh, outputs=status_html)
    
    return page
```

### 7.5 ProcessManager（进程管理器）

`ProcessManager` 是模型服务进程的生命周期控制器。

#### 启动行为

WebUI 启动时：
1. `ServiceRegistry` 从 YAML 加载服务定义。
2. 对于每个 `enabled: true` 且 `start.command` 非空的服务：
   - `ProcessManager` 启动该服务。
   - `HealthChecker` 开始探测。
   - 服务状态更新为 `starting`，随后变为 `running` 或 `unhealthy`。

#### 启动流程

`start.command` 在 YAML 中定义为字符串（如 `"python serve.py --port 8080"`），传递给 `subprocess.Popen` 时使用 `shell=True`。这种方式的优缺点：

- 优势：与 `start.bat` / shell 脚本启动方式一致，用户无需将命令拆分为列表。
- 劣势：shell 注入风险（仅管理员操作配置，风险可控）、信号传递到子进程需要进程组处理（已通过 `preexec_fn=os.setsid` 解决）。
- 替代方案：若需要更安全的启动方式，后续可将 `start.command` 改为 `start.command_args: ["python", "serve.py", "--port", "8080"]` 列表格式，使用 `shell=False`。

```python
def start(service_id: str) -> None:
    service = registry.get(service_id)
    env = os.environ.copy()
    env.update(service.env)
    
    # 通过 CUDA_VISIBLE_DEVICES 分配 GPU
    if service.gpu_assignment:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, service.gpu_assignment))
    
    # YAML 中的 command 是 shell 字符串 → 使用 shell=True
    process = subprocess.Popen(
        service.start_command,
        cwd=service.working_dir,
        env=env,
        stdout=PIPE,
        stderr=PIPE,
        shell=True,                  # 从 YAML 字符串执行
        preexec_fn=os.setsid,        # 创建进程组以便干净终止
    )
    store_pid(service_id, process.pid)
    registry.set_runtime_state(service_id, "starting")
```

> **注意**：`start()` 在守护线程中执行，不在 Gradio 回调线程中直接调用。WebUI 按钮的回调仅负责向内部队列提交启动请求，立即返回"启动中..."状态。ProcessManager 的工作线程从队列取出请求后实际执行 `subprocess.Popen`。

#### 停止流程

```python
def stop(service_id: str) -> None:
    pid = get_pid(service_id)
    timeout = registry.get(service_id).stop_timeout_seconds
    
    registry.set_runtime_state(service_id, "stopping")
    
    # 优雅关闭：向进程组发送 SIGTERM
    os.killpg(os.getpgid(pid), signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # 强制终止：向进程组发送 SIGKILL
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        process.wait()
    
    registry.set_runtime_state(service_id, "stopped")
```

#### 重启

依次执行停止再启动。如果服务处于不健康状态，重启尝试恢复。

#### 停止前保护运行中任务

如果某服务有运行中的任务（SQLite 中状态为 `running`），WebUI 显示确认对话框：
> "服务 [名称] 有 [N] 个正在运行的任务。停止将中断这些任务。是否继续？"

若用户确认，运行中任务标记为 `failed`，原因记录为 `service stopped`（服务已停止）。

#### 日志采集

`ProcessManager` 捕获 stdout/stderr 并写入 `data/logs/services/<service_id>/<timestamp>.log`。WebUI 在服务详情中显示日志尾部（最近 50 行）。

#### 服务意外退出

`ProcessManager` 通过监控线程定期检查 `process.poll()` 来检测意外退出。发生意外退出时，服务标记为 `exited`，并保留退出码和最近的日志行。

### 7.6 HealthChecker（健康检查器）

`HealthChecker` 在后台线程中运行，定时探测每个启用的服务。

#### 检查间隔

健康检查间隔通过 `config/webui.yaml` 的 `refresh.health_check_seconds` 配置（默认 10 秒）。间隔按服务独立计算，某个服务响应慢不会影响其他服务的检查。

#### 最低健康响应约定

实现健康端点的服务应返回 JSON：

```json
{
  "status": "ok",
  "service": "stable-diffusion",
  "model": "default",
  "gpu": [0],
  "message": "ready"
}
```

对于第一阶段占位服务或没有真实 HTTP 后端的服务，`HealthChecker` 在 5 秒内收到任何 2xx HTTP 状态码即认为服务 `running`。

#### 健康状态

- `running`: 端点返回 2xx
- `unhealthy`: 端点返回非 2xx、超时或连接被拒绝
- `unknown`: 端点 URL 为空（已配置但无 URL 的外部托管服务）

服务从 `running` 变为 `unhealthy` 时，WebUI 显示警告并保留日志。

#### 服务状态映射

| 运行时状态 | 健康检查结果 | WebUI 显示 |
|-----------|-------------|-----------|
| `stopped` | 不探测 | 已停止 |
| `starting` | 尚未探测 | 启动中... |
| `running` | 2xx | 运行中 |
| `running` | 非 2xx / 超时 | 不健康 |
| `stopping` | 不探测 | 停止中... |
| `exited` | 不探测 | 已退出（码 N） |

### 7.7 TaskScheduler（任务调度器）

`TaskScheduler` 在 SQLite 中持久化任务状态和队列元数据。

#### 数据库文件

```text
data/tasks.sqlite3
```

#### SQLite 表结构

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,           -- UUID v4
    service_id      TEXT NOT NULL,              -- 引用 services.id
    model_type      TEXT NOT NULL,              -- 如 "stable-diffusion"
    adapter_name    TEXT NOT NULL,              -- 如 "StableDiffusionAdapter"
    request_payload TEXT NOT NULL,              -- JSON 字符串
    target_gpu      TEXT,                       -- JSON 数组或 null，如 "[0]"
    status          TEXT NOT NULL DEFAULT 'queued',
                                                -- queued | running | completed | failed | cancelled
    created_at      TEXT NOT NULL,              -- ISO 8601
    started_at      TEXT,                       -- ISO 8601
    finished_at     TEXT,                       -- ISO 8601
    result_paths    TEXT,                       -- JSON 文件路径数组或 null
    error_summary   TEXT,                       -- 简短描述或 null
    error_detail    TEXT                        -- 完整错误文本或 null
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_service_id ON tasks(service_id);
CREATE INDEX idx_tasks_created_at ON tasks(created_at);
```

#### 任务状态机

```
queued ──> running ──> completed
                │
                ├──> failed
                │
                └──> cancelled（可从除 completed 外的任何状态进入）
```

#### 并发

第一阶段不限制每个服务的并发任务数。如果服务收到多个请求，由其自身处理队列行为。TaskScheduler 记录所有提交及其结果，但不实现速率限制或每个服务的并发槽。

#### 离线服务处理

向状态为 `stopped` 或 `exited` 的服务提交任务时：
- WebUI 警告："服务 [名称] 未在运行。提交到离线服务的任务将保持排队状态，直到服务启动。"
- 任务保存为 `queued` 状态。
- 服务变为 `running` 时，排队任务不会自动提交（这是第二阶段的工作）。
- 用户可以手动取消排队中的任务。

### 7.8 GpuMonitor（GPU 监控器）

`GpuMonitor` 通过 NVML（`nvidia-ml-py` 库）采集 NVIDIA GPU 指标。相比解析 `nvidia-smi` 子进程输出，NVML 在长时间运行的进程中开销更低、数据更结构化。

#### 采集指标

| 指标 | 来源 | 单位 |
|------|------|------|
| GPU 索引 | `nvmlDeviceGetIndex` | 整数 |
| GPU 名称 | `nvmlDeviceGetName` | 字符串 |
| 总显存 | `nvmlDeviceGetMemoryInfo.total` | MiB |
| 已用显存 | `nvmlDeviceGetMemoryInfo.used` | MiB |
| 空闲显存 | `nvmlDeviceGetMemoryInfo.free` | MiB |
| GPU 利用率 | `nvmlDeviceGetUtilizationRates.gpu` | 百分比 |
| 显存利用率 | `nvmlDeviceGetUtilizationRates.memory` | 百分比 |
| 温度 | `nvmlDeviceGetTemperature(GPU)` | 摄氏度 |
| 功耗 | `nvmlDeviceGetPowerUsage` | 毫瓦 |
| 运行中进程 | `nvmlDeviceGetComputeRunningProcesses` | (pid, 已用显存) 列表 |

#### 刷新

指标每 `config/webui.yaml` 的 `refresh.gpu_metrics_seconds`（默认 5 秒）在后台线程中刷新一次。最新快照保存在线程安全的 `GpuSnapshot` 数据类中，供 WebUI 读取。

#### 推荐引擎

基于最新快照计算推荐。排序规则：

1. 过滤可用显存满足需求（>= `service.gpu_min_memory_gb`）的 GPU。
2. 按可用显存降序排列。
3. 平局处理：利用率升序。
4. 再平局处理：温度升序。

结果是一个 GPU 索引的排序列表。排名第一的 GPU 为"推荐"选项。推荐仅为建议。用户可以选择任何 GPU 索引，包括不满足最小显存要求的 GPU。系统在选择低于阈值的 GPU 时显示警告，但不阻止提交。

#### 降级处理

若 NVML 初始化失败（无 NVIDIA 驱动、无 GPU 或未找到库）：
- GpuMonitor 返回空快照。
- GPU 仪表盘显示清晰提示："未检测到 NVIDIA GPU。"
- GPU 推荐返回空列表。
- 任务提交正常进行，不附带 GPU 推荐或警告。

### 7.9 ResultManager（结果管理器）

`ResultManager` 在以下路径写入和跟踪输出：

```text
data/jobs/
```

#### 每个任务的目录结构

```text
data/jobs/tasks/<task_id>/
├── request.json          # 输入负载（提交时保存）
├── response.json         # 输出元数据（完成时保存）
├── logs/
│   ├── submission.log    # 任务创建日志
│   └── completion.log    # 任务完成日志
└── outputs/              # 模型专属输出文件
    ├── result.png        # 示例：图片输出
    ├── result.srt        # 示例：字幕输出
    └── result.txt        # 示例：文本输出
```

#### SQLite 中的结果路径

`tasks` 表的 `result_paths` 列保存一个 JSON 数组，内容为相对于 `data/jobs/tasks/<task_id>/` 的路径。例如：

```json
["outputs/result.png", "outputs/result.txt"]
```

#### 清理

第一阶段不实现自动清理。管理员可手动删除 `data/jobs/` 中的内容。`TaskScheduler` 不引用已被删除的文件。

### 7.10 适配器层

适配器层将 WebUI 逻辑与模型专属 API 隔离。

#### 基础适配器接口

```python
class BaseModelAdapter(ABC):
    @abstractmethod
    def model_type(self) -> str:
        """返回唯一标识符，与 service.model_type 匹配。"""
    
    @abstractmethod
    async def validate(self, payload: dict) -> list[str]:
        """返回校验错误列表（空列表 = 校验通过）。"""
    
    @abstractmethod
    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: list[int] | None,
    ) -> str:
        """提交任务，返回任务 ID 或服务侧引用。"""
    
    @abstractmethod
    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """轮询任务完成状态。返回 {'status': ..., 'result': ..., 'error': ...}。"""
```

#### 第一阶段占位行为

所有四个占位适配器实现该接口但行为相同：

```python
async def submit(self, service_url, payload, target_gpu):
    raise NotImplementedError(
        f"{self.model_type()} 适配器当前为占位状态。"
        "模型推理功能将在未来阶段实现。"
        "请在服务管理标签页中配置并启动一个兼容的服务。"
    )
```

这确保 WebUI、任务队列、配置和服务管理可以在没有真实模型推理的情况下进行端到端测试。用户会看到清晰提示，而不是静默失败。

#### 占位适配器的任务错误处理路径

当用户通过 WebUI 提交任务且适配器是占位状态时，错误处理按以下路径执行：

```text
1. 用户点击"提交"按钮
   │
2. Gradio 回调函数被调用（在 Gradio 线程池中）
   │
3. 回调函数调用 adapter.submit()
   │   → 抛出 NotImplementedError
   │
4. 回调函数内的 try/except 捕获该异常
   │
5. TaskScheduler.update_task_status(task_id, "failed") 被调用
   │   写入 SQLite:
   │     status = "failed"
   │     error_summary = "Stable Diffusion 适配器当前为占位状态"
   │     error_detail = 完整的 traceback 字符串
   │     finished_at = 当前时间
   │
6. ResultManager 记录：
   │   data/jobs/tasks/<task_id>/logs/submission.log
   │   data/jobs/tasks/<task_id>/response.json  (含错误信息)
   │
7. Gradio 回调 UI 组件更新：
   │   - 状态显示为 "失败"
   │   - 显示 error_summary
   │   - 显示"查看日志"按钮
   │
8. 用户可查看任务历史中的失败记录
```

```python
# webui/pages/stable_diffusion.py 中回调的简化代码
async def on_submit(
    service_id: str, payload: dict, target_gpu: str,
    task_id_comp, status_comp, error_comp
):
    task_id = scheduler.create_task(service_id, "stable-diffusion", payload, target_gpu)
    task_id_comp.update(value=task_id)
    status_comp.update(value="提交中...")
    
    try:
        adapter = get_adapter("stable-diffusion")
        result = await adapter.submit(
            service_url=registry.get(service_id).service_url,
            payload=payload,
            target_gpu=parse_gpu_list(target_gpu),
        )
        scheduler.update_task_status(task_id, "completed")
        return [gr.update(value="完成"), gr.update(value="")]
    
    except NotImplementedError as e:
        scheduler.update_task_status(task_id, "failed", error_summary=str(e))
        return [gr.update(value="失败"), gr.update(value=str(e))]
    
    except Exception as e:
        scheduler.update_task_status(task_id, "failed", error_summary=f"提交失败: {e}")
        return [gr.update(value="错误"), gr.update(value=f"提交失败: {e}")]
```

#### `poll_status()` 在第一阶段的使用

第一阶段中 `poll_status()` **没有实际调用者**。任务状态完全通过 SQLite 查询获得（查看任务历史时直接读取 `tasks` 表）。

`poll_status()` 是为第二阶段准备的接口，届时适配器将用它向模型服务的 HTTP API 轮询长时间运行任务的状态。第一阶段占位适配器可以 `pass` 或返回 `{"status": "unknown"}`。

#### ResultManager 集成

ResultManager 与适配器/调度器的协作方式：

- `request.json`: 由 TaskScheduler 在 `create_task()` 时写入，保存原始请求负载。
- `response.json`: 由适配器的 `submit()` 调用者在收到结果后写入，或由占位适配器的异常处理器在失败时写入。
- `outputs/` 目录：由适配器在 `submit()` 中写入（第二阶段）。第一阶段占位不会创建输出文件。
- 目录创建：`ResultManager.ensure_task_dir(task_id)` 在 `create_task()` 时被调用，确保路径存在。

#### Stable Diffusion 适配器说明

Stable Diffusion 适配器设计为后端无关（不绑定 A1111、ComfyUI 或 Diffusers）。第二阶段将支持可插拔后端。第一阶段占位保留以下字段：

- `prompt`（str，提示词）
- `negative_prompt`（str, 可选，反向提示词）
- `width`、`height`（int，宽度/高度）
- `steps`（int，采样步数）
- `cfg_scale`（float，CFG 缩放）
- `seed`（int，-1 表示随机）
- `batch_size`（int，批次大小）
- `target_gpu`（list[int]，目标 GPU）

这些字段在适配器中已记录，但第一阶段不生效。

### 7.11 日志

#### 架构

WebUI 使用 Python 标准 `logging` 模块，所有核心组件采用统一的日志格式。

#### 日志文件

| 组件 | 路径 | 用途 |
|------|------|------|
| WebUI 应用 | `data/logs/webui.log` | 应用级事件、错误、用户操作 |
| 核心服务 | `data/logs/core.log` | ConfigService、ProcessManager、HealthChecker、Scheduler |
| GPU 监控 | `data/logs/gpu.log` | GPU 指标采集和推荐事件 |
| 服务日志 | `data/logs/services/<service_id>/<timestamp>.log` | 被托管模型服务进程的 stdout/stderr |

#### 日志格式

```
2026-06-08 10:15:30,123 [INFO] [core.process_manager] 已启动服务 sd-webui (进程 PID 4731)
2026-06-08 10:15:35,456 [WARN] [core.health_checker] 服务 qwen3-asr 不健康：连接被拒绝
2026-06-08 10:16:01,789 [ERROR] [adapters.stable_diffusion] 占位适配器的 submit 被调用——未实现
```

#### 轮转

通过 `logging.handlers.RotatingFileHandler` 实现，在 `config/webui.yaml` 中配置：

```yaml
logging:
  level: "INFO"
  max_mb_per_file: 10
  backup_count: 5
```

#### WebUI 日志查看器

服务管理标签页包含每个托管服务的日志查看面板（最后 50 行）。核心日志可通过仪表盘上的"查看系统日志"按钮访问。

## 8. 数据流

### 8.1 服务启动与停止流程

#### 内部托管服务启动

1. 用户打开服务管理页面。
2. WebUI 从 `config/services.yaml` 加载服务记录。
3. 用户点击某个服务的"启动"按钮。
4. 回调函数向 ProcessManager 的内部队列提交启动请求，立即返回"启动中..."到 UI。
5. ProcessManager 工作线程从队列取出请求：
   - 解析命令、工作目录、环境和 GPU 分配。
   - 调用 `subprocess.Popen(start.command, shell=True, ...)`。
   - 记录 PID。
   - 发布 `service_state_changed` 事件（`starting`）。
6. HealthChecker 开始探测配置的健康端点。
7. 服务状态变为 `running` 或 `unhealthy`（通过 `set_runtime_state()` + 事件通知）。
8. WebUI 读取最新状态并更新显示。

#### 外部托管服务

若 `start.command` 为空但 `service_url` 已设置，服务标记为"外部托管"，WebUI **隐藏启动/停止按钮**，仅显示状态信息和健康检查结果。

若 `start.command` 和 `service_url` 均为空，WebUI 显示"未配置"状态。

#### 停止流程

1. 用户点击"停止"。
2. 若服务有运行中任务 → 显示确认对话框。
3. 用户确认后，回调向 ProcessManager 提交停止请求。
4. ProcessManager 发送 SIGTERM → 等待 `stop_timeout_seconds` → 若未退出则 SIGKILL。
5. 运行中任务标记为 `failed`（原因：`service stopped`）。
6. 状态更新为 `stopped`。

### 8.2 配置保存流程

1. 用户打开配置标签页。
2. WebUI 将当前 YAML 加载到编辑器。
3. 用户修改字段并点击保存。
4. `ConfigService` 根据 schema 规则校验配置。
5. 校验失败：WebUI 显示字段级错误信息，不保存。
6. 校验通过：WebUI 写入临时 YAML 文件（`config/services.yaml.tmp`）。
7. 重新加载临时文件进行一致性检查。
8. 通过 `os.rename()` 原子替换原文件（Linux 上原子操作）。
9. `ServiceRegistry` 重新加载服务定义。
10. WebUI 显示保存成功和更新后的状态。

### 8.3 任务提交流程

#### 主路径（服务在线 + 适配器已实现 — 第二阶段）

1. 用户打开模型页面或任务提交面板。
2. 用户选择模型/服务和可选的目标 GPU。
3. WebUI 显示当前 GPU 推荐和警告。
4. 用户提交任务。
5. `TaskScheduler` 创建 SQLite 任务记录（`queued` 状态）。
6. `ResultManager.ensure_task_dir(task_id)` 创建 `data/jobs/tasks/<task_id>/` 目录。
7. `request.json` 写入请求负载。
8. 适配器校验负载和服务可用性。
9. 如果服务在线，适配器向服务 HTTP API 提交请求。
10. 任务状态更新为 `running`（`started_at` 记录时间戳）。
11. 适配器通过 `poll_status()` 轮询完成状态（第二阶段）。
12. 结果路径和最终状态持久化（`completed` / `failed`）。
13. `response.json` 写入。
14. WebUI 显示任务结果或失败信息。

#### 占位适配器路径（第一阶段）

1-6 同上。
7. Gradio 回调调用 `adapter.submit()`。
8. 适配器抛出 `NotImplementedError`。
9. 回调的 `try/except` 捕获异常。
10. `TaskScheduler.update_task_status()` 写入：
    - `status = "failed"`
    - `error_summary = "Stable Diffusion 适配器当前为占位状态"`
    - `error_detail = traceback 文本`
    - `finished_at = 当前时间`
11. `ResultManager` 写入 `logs/submission.log` 和 `response.json`（含错误信息）。
12. WebUI 显示失败状态和错误摘要。

#### 离线服务路径

1-6 同上。
7. WebUI 检查服务状态 → `stopped` 或 `exited`。
8. WebUI 显示静默警告："服务 [名称] 未在运行。任务将保持排队状态直到服务启动。"
9. 用户可选择"仍要提交"或"取消"。
10. 若提交，任务保持 `queued` 状态。
11. 用户后续可手动取消排队中的任务。

#### 无效负载路径

1-5 同上。
6. 适配器 `validate()` 返回错误列表。
7. WebUI 显示字段级校验错误，任务**不**创建。

### 8.4 GPU 推荐流程

1. `GpuMonitor` 刷新 GPU 指标。
2. 调度器接收任务需求（如模型类型和可选的显存预估）。
3. 推荐引擎对 GPU 排序。
4. WebUI 显示推荐 GPU 和备选方案。
5. 用户可选择接受推荐或手动选择其他 GPU。
6. 选定的 GPU 随任务存储并传递给服务适配器。

## 9. 错误处理

### 配置错误

- YAML 解析错误：显示解析错误信息，不保存。
- 缺少必填服务字段：显示字段级校验错误。
- 服务 ID 重复：拒绝保存。
- 端口或 URL 不合法：拒绝保存。
- 命令路径不合法：拒绝保存，或显示服务启动失败。

### 服务错误

- 服务启动失败：显示命令、工作目录和最近的日志片段。
- 服务意外退出：标记为已停止/不健康，保留日志。
- 健康检查失败：标记服务不健康，但保留上次已知状态。
- 服务端点返回非 2xx：将响应体摘要保存到任务错误信息中。

### 任务错误

- 离线服务：提交前警告；如果用户继续，任务保持排队状态或以清晰消息标识失败。
- 无效负载：快速失败，提供字段级校验。
- 适配器未实现：返回清晰消息，说明模型适配器已为后续阶段预留。
- 结果写入失败：标记任务失败，包含存储路径错误。
- GPU 不可用：警告用户，允许手动覆盖，除非服务拒绝请求。

### 面向用户的错误信息格式

WebUI 中显示的错误应包含：

- 简短摘要
- 受影响的服务或任务 ID
- 系统已采取的操作
- 建议的下一步操作
- 可查看日志的链接或按钮（如适用）

## 10. 测试策略

第一阶段测试应避免需要真实的 AI 模型推理。

### 单元测试

- YAML 校验和安全保存
- 服务注册中心加载
- 服务 ID 唯一性校验
- GPU 推荐排序
- 任务状态转换
- 结果路径生成
- 适配器请求校验
- 错误信息规范化

### 集成测试

- 从配置文件启动模拟 HTTP 服务
- 对模拟服务进行健康检查
- 停止和重启模拟服务
- 向模拟服务提交任务
- 在 SQLite 中持久化任务历史
- 验证结果文件写入 `data/jobs/`

### 手动测试清单

- 从局域网浏览器打开 WebUI
- 查看服务列表和 GPU 仪表盘
- 添加或编辑服务配置
- 保存无效配置并确认被拒绝
- 启动模拟服务
- 确认健康状态更新
- 停止并重启服务
- 向占位适配器提交任务，确认清晰的未实现提示
- 确认日志和任务历史可见
- 确认结果目录结构已创建

## 11. 第一阶段里程碑

### 里程碑 1：项目骨架

- 按第 6 节定义创建项目目录结构。
- 添加 `config/` 和 `data/` 目录并放置 `.gitkeep` 文件。
- 在 `webui/`、`core/`、`adapters/` 下创建核心包布局。
- 定义 `pyproject.toml`（项目元数据）。
- 编写 README 快速入门说明。
- 实现 CLI 入口点：`python main.py`（或通过 `pip install -e .` 使用 `webui` 命令）。

#### CLI 入口点

```text
用法: main.py [-h] [--host HOST] [--port PORT] [--config CONFIG] [--log-level LEVEL]

Gradio 统一 AI WebUI

可选参数:
  -h, --help            显示此帮助信息并退出
  --host HOST           绑定地址（默认: 0.0.0.0）
  --port PORT           监听端口（默认: 7860）
  --config CONFIG       配置目录（默认: config/）
  --log-level LEVEL     日志级别: DEBUG, INFO, WARNING, ERROR（默认: INFO）
```

CLI 参数优先于 `config/webui.yaml` 中对应的设置。

#### Python 依赖（pyproject.toml）

```toml
[project]
name = "gradio-universal-webui"
version = "0.1.0"
requires-python = ">=3.10"

dependencies = [
    "gradio>=5.0",
    "pyyaml>=6.0",
    "nvidia-ml-py>=12.0",       # GPU 监控的 NVML 绑定
    "aiohttp>=3.9",              # 健康检查和任务提交的异步 HTTP 客户端
    "aiosqlite>=0.20",           # 异步 SQLite 访问
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]
```

### 里程碑 2：配置和服务注册中心

- 定义 `config/services.yaml`
- 实现 `ConfigService`
- 实现 `ServiceRegistry`
- 添加服务定义校验
- 添加 WebUI 配置编辑器

### 里程碑 3：服务管理

- 实现 `ProcessManager`
- 实现启动、停止、重启
- 采集日志
- 在 WebUI 中添加服务状态表
- 添加健康检查

### 里程碑 4：任务队列和结果存储

- 初始化 SQLite 表结构
- 实现任务创建和状态更新
- 添加任务历史界面
- 实现 `ResultManager`
- 在 `data/jobs/` 下存储请求/响应元数据

### 里程碑 5：GPU 监控和推荐

- 采集 NVIDIA GPU 指标
- 显示 GPU 仪表盘
- 按可用显存、利用率和温度对 GPU 排序
- 允许用户手动覆盖推荐 GPU

### 里程碑 6：适配器占位

- 定义基础适配器接口
- 为 Stable Diffusion、Qwen3ASR、WhisperX 和 FastWhisper 添加占位适配器
- 对不支持的模型逻辑返回清晰的未实现消息
- 预留服务 URL 和任务元数据供后续实现使用

### 里程碑 7：第一阶段验证

- 运行自动化测试
- 运行模拟服务集成测试
- 验证局域网访问 WebUI
- 验证服务启动/停止/重启
- 验证配置持久化
- 验证任务持久化
- 验证 GPU 仪表盘

## 12. 模块化开发文档

主设计文档定义整体架构和组件关系。**具体到可执行的实现细节在以下模块文档中：**

| # | 模块 | 文件 | 行数 | 内容 |
|---|------|------|------|------|
| 1 | 项目骨架与 CLI | [modules/01-bootstrap-cli.md](modules/01-bootstrap-cli.md) | 272 | main.py, 目录结构, pyproject.toml, 启动序列 |
| 2 | 配置系统 | [modules/02-configuration.md](modules/02-configuration.md) | 316 | ConfigService, YAML schema, 校验规则 |
| 3 | 服务注册与事件 | [modules/03-service-registry-eventbus.md](modules/03-service-registry-eventbus.md) | 200 | ServiceRegistry, EventBus, 线程安全 |
| 4 | 日志系统 | [modules/04-logging.md](modules/04-logging.md) | 174 | logging 配置, 轮转, 服务日志 |
| 5 | 进程管理与健康检查 | [modules/05-process-manager-health-checker.md](modules/05-process-manager-health-checker.md) | 320 | ProcessManager, HealthChecker, 后台线程 |
| 6 | 任务管理与结果存储 | [modules/06-task-scheduler-result-manager.md](modules/06-task-scheduler-result-manager.md) | 341 | TaskScheduler (SQLite), ResultManager |
| 7 | GPU 监控 | [modules/07-gpu-monitor.md](modules/07-gpu-monitor.md) | 273 | GpuMonitor (NVML), 推荐引擎 |
| 8 | 适配器框架 | [modules/08-adapter-framework.md](modules/08-adapter-framework.md) | 244 | BaseModelAdapter, 占位适配器 |
| 9 | WebUI 主程序组装 | [modules/09-webui-assembly.md](modules/09-webui-assembly.md) | 202 | app.py, state.py, 页面注册 |
| 10 | WebUI 页面 | [modules/10-webui-pages.md](modules/10-webui-pages.md) | 733 | 9 个页面文件的完整布局和回调 |

**模块间依赖关系和推荐实现顺序** 见 [modules/README.md](modules/README.md)。

## 13. 向第二阶段演进

第二阶段应将占位适配器升级为真实的 HTTP 模型服务。

推荐的第二阶段工作：

- 定义稳定的模型服务 HTTP API
- 为选定后端实现 Stable Diffusion 适配器
- 研究和实现 Qwen3ASR HTTP 服务
- 研究和实现 WhisperX HTTP 服务
- 研究和实现 FastWhisper HTTP 服务
- 添加服务日志流式传输
- 添加任务取消功能
- 添加每个模型的配置表单
- 添加可选的 Docker Compose 部署
- 若对外开放局域网，添加认证功能

## 14. 开放决策

- Python 环境策略：venv、conda 还是容器化服务
- Stable Diffusion 后端选型
- Qwen3ASR 服务抽取策略
- WhisperX 和 FastWhisper 实现来源
- 未来的工作流编排应在 WebUI 内部实现还是外部实现

以上开放决策故意放在第一阶段之外。第一阶段架构通过服务配置、进程管理和适配器接口将这些决策隔离。
