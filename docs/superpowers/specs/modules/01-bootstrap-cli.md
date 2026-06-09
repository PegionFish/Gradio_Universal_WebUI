# 模块 1：项目骨架与 CLI

## 用途

创建项目目录结构、定义 Python 包布局、实现 CLI 入口点。这是所有其他模块的构建基础。

## 依赖

无外部依赖。仅在 Python >=3.10 环境下需要 `argparse`（标准库）。

## 产出物

```
Gradio_Universal_WebUI/
├── main.py                     # CLI 入口
├── pyproject.toml              # 项目元数据与依赖声明
├── config/                     # 配置文件（*.yaml + .gitkeep）
├── data/                       # 运行时数据（.gitkeep）
│   ├── logs/                   # 日志目录
│   └── jobs/                   # 任务结果目录
├── webui/                      # Gradio UI 包
│   ├── __init__.py
│   ├── app.py                  # 占位
│   ├── pages/                  # 标签页面包
│   │   ├── __init__.py
│   │   ├── dashboard.py
│   │   ├── services.py
│   │   ├── tasks.py
│   │   ├── gpu.py
│   │   ├── config.py
│   │   ├── stable_diffusion.py
│   │   ├── qwen3_asr.py
│   │   ├── whisperx.py
│   │   └── fastwhisper.py
│   ├── components/
│   │   ├── __init__.py
│   │   ├── service_table.py
│   │   ├── task_list.py
│   │   ├── gpu_dashboard.py
│   │   ├── config_editor.py
│   │   └── error_display.py
│   └── state.py
├── core/
│   ├── __init__.py             # 核心服务单例初始化
│   ├── config_service.py
│   ├── service_registry.py
│   ├── event_bus.py
│   ├── process_manager.py
│   ├── health_checker.py
│   ├── task_scheduler.py
│   ├── gpu_monitor.py
│   └── result_manager.py
├── adapters/
│   ├── __init__.py
│   ├── base.py
│   ├── stable_diffusion.py
│   ├── qwen3_asr.py
│   ├── whisperx.py
│   └── fastwhisper.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_config_service.py
    ├── test_service_registry.py
    ├── test_event_bus.py
    ├── test_process_manager.py
    ├── test_health_checker.py
    ├── test_task_scheduler.py
    ├── test_gpu_monitor.py
    ├── test_result_manager.py
    └── test_adapters.py
```

### 文件命名规则

- `webui/pages/` 下每个文件对应一个 Gradio 标签页，文件名小写蛇形
- `core/` 下文件名为对应类的蛇形命名
- `adapters/` 下文件名为模型类型蛇形命名

### 文件占位规则

所有 `.py` 文件初始状态仅包含:

```python
# <模块路径> — 用途简述
# 此文件为占位，具体实现在对应模块设计文档中定义
__all__ = []
```

`__init__.py` 文件不做任何导出，仅保持包结构完整性。

## CLI 入口点

### main.py

```python
#!/usr/bin/env python3
"""Gradio 统一 AI WebUI — CLI 入口"""

import argparse
import sys
import os


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webui",
        description="Gradio 统一 AI WebUI — 管理本地 AI 负载的一站式前端套件",
    )
    parser.add_argument("--host", default=None, help="绑定地址（默认: 0.0.0.0）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认: 7860）")
    parser.add_argument("--config", default=None, help="配置目录（默认: config/）")
    parser.add_argument("--log-level", default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别（默认: INFO）")
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动序列 (8 步)。"""
    # 1. 解析 CLI 参数
    parser = build_parser()
    args = parser.parse_args(argv)

    # 2. 初始化日志系统
    #    (实现在 模块 4：日志系统)

    # 3. 初始化核心服务
    #    core.setup_core(config_dir=args.config or "config/")
    #    (创建 ConfigService、ServiceRegistry、ProcessManager 等实例)

    # 4. 加载配置并初始化 ServiceRegistry
    #    (实现在 模块 2：配置系统、模块 3：服务注册与事件)

    # 5. 启动后台线程
    #    core.process_manager.start()           — 工作线程
    #    core.process_manager.start_watcher()   — 进程监控
    #    health_checker.start()                 — 健康探测
    #    gpu_monitor.start()                    — GPU 采集
    #    (实现在 模块 5：进程管理与健康检查)
    #    (实现在 模块 7：GPU 监控)

    # 6. Auto-start 启用的服务
    #    (实现在 模块 5)

    # 7. 构建并启动 WebUI
    #    (实现在 模块 9：WebUI 主程序组装)

    # 8. 关闭清理
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> **注意**：`main()` 中的步骤注释标志了各模块的集成点。实现每个模块时逐步填充对应步骤。

## pyproject.toml

```toml
[project]
name = "gradio-universal-webui"
version = "0.1.0"
description = "基于 Gradio 的统一 AI 前端套件 — 管理本地 AI 负载"
requires-python = ">=3.10"
license = {text = "AGPL-3.0-only"}

dependencies = [
    "gradio>=5.0",
    "pyyaml>=6.0",
    "nvidia-ml-py>=12.0",
    "aiohttp>=3.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["webui*", "core*", "adapters*"]
```

## 启动序列

`main.py` 的 `main()` 函数按以下顺序执行：

```text
1. 解析 CLI 参数 (argparse)
   │   --host, --port, --config, --log-level
   │   CLI 参数优先于 config/webui.yaml 中对应的字段
   │
2. 初始化日志系统
   │   根据 config/webui.yaml 中的 logging 段
   │   配置 RotatingFileHandler + StreamHandler
   │   若配置文件不存在则使用硬编码默认值
   │
3. 初始化核心服务 (core.setup_core)
   │   创建 ConfigService（使用 CLI 指定的 config_dir）
   │   创建 ServiceRegistry、ProcessManager 等实例
   │   ProcessManager 工作线程尚未启动
   │
4. 加载配置并初始化 ServiceRegistry
   │   config/ 目录不存在 → 创建并写入默认配置
   │   config/webui.yaml 不存在 → 创建默认值
   │   config/services.yaml 不存在 → 创建空服务列表
   │   配置文件存在但 YAML 解析失败 → 打印错误并退出(exit 1)
   │   配置文件存在但校验失败 → 打印错误并退出(exit 1)
   │   registry.load_from_config() 填充服务记录
   │
5. 启动后台守护线程
   │   core.process_manager.start()       → 启动工作线程（队列处理）
   │   core.process_manager.start_watcher() → 每 15 秒检查进程
   │   HealthChecker.start()              → 每 N 秒探测
   │   GpuMonitor.start()                 → 每 N 秒采集指标
   │
6. Auto-start 启用的服务
   │   对 ServiceRegistry 中 enabled=true 且 start.command 非空的服务:
   │   ProcessManager.start(service_id)   → 异步提交到工作队列
   │   HealthChecker 自动开始探测该服务
   │
7. 构建并启动 WebUI
   │   from webui.app import create_app, launch_app
   │   app = create_app()
   │   launch_app(app, host, port)
   │   → 此调用阻塞，直到用户 Ctrl+C
   │
8. 关闭清理
   │   HealthChecker.stop()    → 停止探测线程
   │   GpuMonitor.stop()       → 停止采集线程
   │   ProcessManager.stop_all() → 对所有运行中服务:
   │       先 SIGTERM (stop_timeout_seconds)
   │       超时后 SIGKILL
   │   关闭日志处理器
   │   退出 (exit 0)
```

## 配置默认值生成规则

### config/webui.yaml 默认值

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

### config/services.yaml 默认值

```yaml
services: []
```

> 初始状态为空的 services 列表。不自动填充四个占位服务，因为首次运行时用户应通过 WebUI 配置编辑器添加，而不是从默认模板创建无用条目。

## 验收标准

1. `python main.py --help` 显示完整的帮助信息
2. `python main.py` 在配置目录不存在时自动创建 config/ 和 data/
3. `python main.py` 在配置文件不存在时创建默认 YAML 文件
4. `python main.py --port 8080` 覆盖配置中的端口设置
5. 目录结构符合上述定义，所有 `__init__.py` 存在
6. `pip install -e .` 可安装包
7. 启动序列在第 6 步 auto-start 后等待，第 7 步启动 WebUI
