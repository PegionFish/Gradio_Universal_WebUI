# CLAUDE.md

本文件为 Claude Code 在此仓库工作的上下文指引。

## 项目概要

**Gradio Universal WebUI** — 基于 Gradio 6.x 的统一 AI 前端套件，管理 Stable Diffusion / Qwen3 ASR / WhisperX / FastWhisper 四大本地 AI 工作负载。

- **开发阶段**：Phase 1-4 全部完成
- **当前提交数**：36
- **测试**：177 tests，100% pass（pytest + pytest-asyncio）
- **Python 版本**：≥3.10

## 架构要点

### 三层架构

```
WebUI 层 (Gradio) → 适配器层 (HTTP clients) → 模型服务 (独立 HTTP API)
        ↓
核心服务层 (12 个守护线程模块，与 UI 完全解耦)
```

### 关键设计决策

1. **所有后台服务是守护线程**（HealthChecker、GpuMonitor、ProcessManager、SystemMonitor），与 Gradio 标签页切换无关
2. **配置写入用 `tmp + rename` 原子模式**，防止数据损坏
3. **EventBus 是同步线程安全总线**，EventBuffer 基于 cursor 提供增量轮询
4. **任务调度器 SQLite WAL 模式** + `threading.Lock` 保证并发安全
5. **适配器全部是真实 HTTP 客户端**（不再有 NotImplementedError 占位）
6. **每个模型服务独立 HTTP 端口**，通过 `services/` 包装脚本启动

### 核心模块（12 个，`core/` 目录）

| 文件 | 职责 |
|------|------|
| `config_service.py` | YAML 读写/校验/原子写入 |
| `service_registry.py` | 线程安全服务注册 + 状态事件 |
| `event_bus.py` | 同步事件总线，单一全局 `bus` 实例 |
| `process_manager.py` | 服务进程启动/停止/重启 + 日志流 |
| `health_checker.py` | 异步 aiohttp HTTP 健康探测 |
| `task_scheduler.py` | SQLite 任务队列 + 重试/取消/统计 |
| `result_manager.py` | `data/jobs/` 任务结果文件管理 |
| `gpu_monitor.py` | NVML GPU 指标采集 + 推荐排序 |
| `gpu_allocator.py` | GPU 显存预留追踪 + 冲突检测 |
| `system_monitor.py` | psutil CPU/内存/磁盘监控 + 告警 |
| `ws_bridge.py` | EventBus → EventBuffer 增量轮询桥 |
| `auth.py` | 令牌认证管理器（会话管理） |

### 核心服务初始化

通过 `core.setup_core()` 集中初始化，模块级变量在 `main.py` 启动序列步骤 3 中赋值。所有 WebUI 页面通过 `from core import registry, scheduler, ...` 访问这些变量——在 `create_app()` 之前已初始化完毕。

### 适配器注册

模块导入时自动完成注册（`register_adapter("model-type", AdapterClass)`），在 `main.py` 步骤 4b 中通过 `import adapters.*` 触发。

## 提交规范

每个 commit 只做一件事，前缀领域标签：

```
[组件]     webui/components/
[适配器]   adapters/
[服务]     services/
[页面]     webui/pages/
[日志]     logging
[调度器]   task_scheduler
[GPU]      gpu_monitor/gpu_allocator
[系统]     system_monitor
[认证]     auth
[实时]     ws_bridge/EventBuffer
[部署]     Docker/Compose
[测试]     tests/
```

示例：`[适配器] Qwen3ASR 真实 HTTP 实现`

## 交互原则

### 必须做到

- 每个功能完成后立即推送 GitHub（`git push origin main`）
- 每件独立工作单独 commit，不打包巨型 commit
- 提交前必须运行全量测试（`pytest tests/ -q`）
- 代码注释使用简体中文
- 遵循项目既有代码风格（导入顺序、命名约定）

### 架构约束

- WebUI 只读不写后台数据——所有写入通过核心服务 API
- 事件处理器必须轻量（不阻塞超过 1 秒）
- 新功能使用已有组件库（`webui/components/`）复用
- 禁止新增自研方案当已有生态成熟方案时

### 文件编码

- 所有源文件 UTF-8 无 BOM
- 配置/数据文件 UTF-8
