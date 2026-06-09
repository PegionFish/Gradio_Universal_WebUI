# 统一 AI WebUI — 模块设计文档索引

此为第一阶段各模块的详细实现规格文档。每个模块独立成文，包含数据结构、API 接口、实现细节和验收标准，可直接用于编码 Session。

## 模块依赖关系

```text
模块 1: 项目骨架与 CLI         (无依赖)
  └── 模块 2: 配置系统           (依赖模块 1)
  └── 模块 4: 日志系统           (依赖模块 1)
      └── 模块 3: 服务注册与事件   (依赖模块 2)
          ├── 模块 5: 进程管理与健康检查 (依赖模块 3)
          ├── 模块 6: 任务管理与结果存储 (依赖模块 1, 3)
          ├── 模块 7: GPU 监控    (依赖模块 1)
          └── 模块 8: 适配器框架   (依赖模块 3)
              └── 模块 9: WebUI 主程序组装 (依赖全部以上)
                  └── 模块 10: WebUI 页面 (依赖模块 9)
```

## 推荐实现顺序

| 顺序 | 模块 | 预计工时 | 产出物 |
|------|------|---------|--------|
| 1 | 项目骨架与 CLI | 1 Session | main.py, pyproject.toml, 目录结构, CLI 参数 |
| 2 | 配置系统 | 1 Session | ConfigService, YAML schema, 校验规则 |
| 3 | 服务注册与事件 | 1 Session | ServiceRegistry, EventBus, 事件类型 |
| 4 | 日志系统 | 0.5 Session | logging 配置, 日志轮转, 日志文件布局 |
| 5 | 进程管理与健康检查 | 1-2 Sessions | ProcessManager, HealthChecker, 后台线程 |
| 6 | 任务管理与结果存储 | 1 Session | TaskScheduler (SQLite), ResultManager |
| 7 | GPU 监控 | 1 Session | GpuMonitor (NVML), 推荐引擎 |
| 8 | 适配器框架 | 0.5 Session | BaseModelAdapter, 占位适配器 |
| 9 | WebUI 主程序组装 | 1 Session | app.py, state.py, 组件注册 |
| 10 | WebUI 页面 | 2 Sessions | 9 个页面文件, 交互回调 |

**总计约 10-12 个 Session。** 每个 Session 独立可交付，不影响其他模块的正常开发。

## 模块链接

| # | 模块 | 文件 |
|---|------|------|
| 1 | 项目骨架与 CLI | [01-bootstrap-cli.md](01-bootstrap-cli.md) |
| 2 | 配置系统 | [02-configuration.md](02-configuration.md) |
| 3 | 服务注册与事件 | [03-service-registry-eventbus.md](03-service-registry-eventbus.md) |
| 4 | 日志系统 | [04-logging.md](04-logging.md) |
| 5 | 进程管理与健康检查 | [05-process-manager-health-checker.md](05-process-manager-health-checker.md) |
| 6 | 任务管理与结果存储 | [06-task-scheduler-result-manager.md](06-task-scheduler-result-manager.md) |
| 7 | GPU 监控 | [07-gpu-monitor.md](07-gpu-monitor.md) |
| 8 | 适配器框架 | [08-adapter-framework.md](08-adapter-framework.md) |
| 9 | WebUI 主程序组装 | [09-webui-assembly.md](09-webui-assembly.md) |
| 10 | WebUI 页面 | [10-webui-pages.md](10-webui-pages.md) |
