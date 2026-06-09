# Gradio Universal WebUI

基于 Gradio 的统一 AI 前端套件 — 管理本地 AI 负载的一站式解决方案。

## 项目状态

**第一阶段 - 框架开发** (进行中)

已完成模块1：项目骨架与CLI

## 第一阶段功能

### 已实现 (模块1)
- ✅ 项目目录结构：`config/`, `data/`, `core/`, `webui/`, `adapters/`, `tests/`
- ✅ CLI入口：`main.py` 支持 `--host`, `--port`, `--config`, `--log-level`参数
- ✅ 基础配置文件：`config/webui.yaml`, `config/services.yaml`
- ✅ 依赖定义：`pyproject.toml` 包含所有必需依赖
- ✅ 完整的Python包结构

### 待实现 (后续模块)
- 模块2：配置系统 (`ConfigService`)
- 模块3：服务注册与事件 (`ServiceRegistry`, `EventBus`)
- 模块4：日志系统
- 模块5：进程管理与健康检查 (`ProcessManager`, `HealthChecker`)
- 模块6：任务管理与结果存储 (`TaskScheduler`, `ResultManager`)
- 模块7：GPU监控 (`GpuMonitor`)
- 模块8：适配器框架
- 模块9：WebUI主程序组装
- 模块10：WebUI页面实现

## 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/PegionFish/Gradio_Universal_WebUI.git
cd Gradio_Universal_WebUI
```

### 2. 安装依赖
```bash
pip install -e .
```

### 3. 首次运行
```bash
python main.py
```

### 4. 访问WebUI
默认地址：http://localhost:7860

## 配置说明

### 核心配置文件
1. **`config/webui.yaml`** - WebUI服务器设置
   ```yaml
   server:
     host: "0.0.0.0"
     port: 7860
     public_url: ""
   
   refresh:
     health_check_seconds: 10
     gpu_metrics_seconds: 5
     task_status_seconds: 15
   
   logging:
     level: "INFO"
     max_mb_per_file: 10
     backup_count: 5
     directory: "data/logs/"
   ```

2. **`config/services.yaml`** - 模型服务定义
   ```yaml
   services: []  # 初始为空，通过WebUI添加
   ```

### 命令行参数
参数优先级：CLI参数 > 配置文件
```bash
python main.py --host 0.0.0.0 --port 8080 --config ./myconfig --log-level DEBUG
```

## 开发要求

- Python 3.10+
- Git (用于版本控制)
- 可选：NVIDIA GPU + 驱动 (用于GPU监控)

## 测试

```bash
# 安装开发依赖
pip install -e .[dev]

# 运行测试
pytest
```

## 目录结构

```
Gradio_Universal_WebUI/
├── main.py                     # CLI入口
├── pyproject.toml              # 项目元数据与依赖
├── config/                     # 配置文件
│   ├── webui.yaml             # WebUI服务器设置
│   └── services.yaml          # 模型服务定义
├── data/                       # 运行时数据
│   ├── logs/                  # 日志目录
│   └── jobs/                  # 任务结果目录
├── utils/                     # 工具脚本
│   └── git_auto_push.py      # 自动Git提交
├── webui/                     # Gradio UI包
│   ├── app.py                # 应用组装
│   ├── state.py              # 共享状态管理
│   ├── pages/                # 标签页面
│   └── components/           # 可重用组件
├── core/                      # 核心服务
│   ├── config_service.py     # 配置服务
│   ├── service_registry.py   # 服务注册中心
│   ├── event_bus.py          # 事件总线
│   ├── process_manager.py    # 进程管理器
│   ├── health_checker.py     # 健康检查器
│   ├── task_scheduler.py     # 任务调度器
│   ├── gpu_monitor.py        # GPU监控器
│   └── result_manager.py     # 结果管理器
├── adapters/                  # 模型适配器
│   ├── base.py               # 抽象基类
│   ├── stable_diffusion.py   # Stable Diffusion适配器
│   ├── qwen3_asr.py          # Qwen3 ASR适配器
│   ├── whisperx.py           # WhisperX适配器
│   └── fastwhisper.py        # FastWhisper适配器
├── tests/                     # 测试文件
│   ├── test_config_service.py
│   ├── test_service_registry.py
│   ├── test_event_bus.py
│   ├── test_process_manager.py
│   ├── test_health_checker.py
│   ├── test_task_scheduler.py
│   ├── test_gpu_monitor.py
│   ├── test_result_manager.py
│   └── test_adapters.py
└── docs/                     # 文档
    └── superpowers/specs/   # 设计文档
```

## 技术栈

- **前端**: Gradio 5.x (Python WebUI框架)
- **配置**: YAML + 校验 (PyYAML)
- **监控**: GPU指标 (NVML via nvidia-ml-py)
- **持久化**: SQLite (任务历史) + 文件系统 (结果存储)
- **异步**: aiohttp (HTTP客户端)
- **测试**: pytest + pytest-asyncio

## 下一步工作

按照模块依赖顺序实现剩余功能：

1. 模块2：配置系统
2. 模块3：服务注册与事件
3. 模块4：日志系统
4. 模块5：进程管理与健康检查
5. 模块6：任务管理与结果存储
6. 模块7：GPU监控
7. 模块8：适配器框架
8. 模块9：WebUI主程序组装
9. 模块10：WebUI页面实现

## 许可证

AGPL-3.0-only - 请查看 [LICENSE](LICENSE) 文件了解详情。