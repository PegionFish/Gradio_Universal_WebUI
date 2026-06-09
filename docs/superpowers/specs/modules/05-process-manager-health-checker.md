# 模块 5：进程管理与健康检查

## 用途

`ProcessManager` 管理模型服务进程的生命周期（启动、停止、重启、监控）。`HealthChecker` 定时探测 HTTP 服务健康状况并更新运行状态。

## 依赖

- **模块 1**：项目骨架（日志目录 `data/logs/services/`）
- **模块 3**：ServiceRegistry（运行时状态管理）、EventBus（状态变更通知）
- **模块 4**：日志系统（`logging.getLogger`）

## ProcessManager

### 文件位置

`core/process_manager.py`

### 线程模型

服务启动/停止/重启操作通过一个**内部队列**提交给 ProcessManager 的**工作线程**执行。Gradio 回调仅负责向队列提交请求并立即返回，不阻塞主线程。

```python
import queue
import threading

class ProcessManager:
    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}
        self._log_files: dict[str, str] = {}
        self._shutdown = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="proc-mgr")
        self._worker.start()
    
    def _worker_loop(self):
        """工作线程循环，从队列取出请求执行。"""
        while not self._shutdown.is_set():
            try:
                action, service_id = self._queue.get(timeout=1)
                if action == "start":
                    self._do_start(service_id)
                elif action == "stop":
                    self._do_stop(service_id)
                elif action == "restart":
                    self._do_stop(service_id)
                    self._do_start(service_id)
            except queue.Empty:
                continue
```

### start(service_id) —— 异步提交

```python
def start(self, service_id: str):
    """异步启动服务。Gradio 回调可直接调用，不阻塞。"""
    self._queue.put(("start", service_id))
    registry.set_runtime_state(service_id, "starting")
```

### _do_start(service_id) —— 工作线程中实际执行

```python
def _do_start(self, service_id: str):
    service = registry.get(service_id)
    if not service or not service.start_command or not service.working_dir:
        logger.error("服务 %s 缺少启动配置", service_id)
        registry.set_runtime_state(service_id, "exited")
        return
    
    env = os.environ.copy()
    env.update(service.env)
    if service.gpu_assignment:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, service.gpu_assignment))
    
    # 创建日志文件
    log_path = self._open_service_log(service_id)
    log_file = open(log_path, "w", encoding="utf-8")
    
    try:
        process = subprocess.Popen(
            service.start_command,
            shell=True,
            cwd=service.working_dir,
            env=env,
            stdout=log_file,
            stderr=log_file,
            preexec_fn=os.setsid,     # 进程组用于干净终止
        )
        self._processes[service_id] = process
        self._log_files[service_id] = log_path
        registry.set_pid(service_id, process.pid)
    except FileNotFoundError:
        logger.error("服务 %s 启动失败: 命令 '%s' 未找到", service_id, service.start_command)
        registry.set_runtime_state(service_id, "exited")
    except PermissionError:
        logger.error("服务 %s 启动失败: 无权执行 '%s'", service_id, service.start_command)
        registry.set_runtime_state(service_id, "exited")
```

### stop(service_id) —— 异步提交

```python
def stop(self, service_id: str):
    """异步停止服务。"""
    self._queue.put(("stop", service_id))
    registry.set_runtime_state(service_id, "stopping")
```

### _do_stop(service_id)

```python
def _do_stop(self, service_id: str):
    process = self._processes.get(service_id)
    if not process:
        registry.set_runtime_state(service_id, "stopped")
        return
    
    timeout = registry.get(service_id).stop_timeout_seconds
    
    try:
        # SIGTERM 到进程组
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # 超时后强制 SIGKILL
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait()
    
    self._processes.pop(service_id, None)
    registry.set_runtime_state(service_id, "stopped")
    
    # 关闭日志文件句柄
    log_file = self._log_files.get(service_id)
    if log_file:
        logger.info("服务 %s 日志已保存: %s", service_id, log_file)
```

### restart(service_id)

```python
def restart(self, service_id: str):
    """异步重启服务。"""
    self._queue.put(("restart", service_id))
    registry.set_runtime_state(service_id, "stopping")
```

### watcher 线程 —— 检测意外退出

```python
def start_watcher(self):
    """启动进程监控线程，每 15 秒检查存活。"""
    def _watch():
        while not self._shutdown.is_set():
            for service_id, process in list(self._processes.items()):
                if process.poll() is not None:
                    # 进程已退出
                    exit_code = process.returncode
                    logger.warning("服务 %s 意外退出 (exit code: %s)", service_id, exit_code)
                    self._processes.pop(service_id, None)
                    registry.set_runtime_state(service_id, "exited")
            self._shutdown.wait(15)
    
    watcher = threading.Thread(target=_watch, daemon=True, name="proc-watcher")
    watcher.start()
```

### stop_all() —— 关闭时调用

```python
def stop_all(self):
    """停止所有运行中服务。在进程关闭时调用。"""
    for service_id in list(self._processes.keys()):
        self._do_stop(service_id)
```

### 停止前保护运行中任务

在服务管理页面的停止按钮回调中实现（非 ProcessManager 职责）：

```python
# webui/pages/services.py 中:
def on_stop_click(service_id: str):
    running_tasks = scheduler.get_running_tasks(service_id)
    if running_tasks:
        # 返回警告让 Gradio 显示确认对话框
        return gr.update(visible=True), f"服务有 {len(running_tasks)} 个运行中任务，停止将中断它们。"
    else:
        process_manager.stop(service_id)
        return gr.update(visible=False), ""
```

## HealthChecker

### 文件位置

`core/health_checker.py`

### 实现

```python
import aiohttp
import asyncio
import threading
import logging

logger = logging.getLogger("core.health_checker")


class HealthChecker:
    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
    
    def start(self, interval_seconds: int = 10):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval_seconds,),
            daemon=True,
            name="health-checker",
        )
        self._thread.start()
        logger.info("HealthChecker 已启动 (间隔 %ds)", interval_seconds)
    
    def stop(self):
        self._running = False
    
    def _run_loop(self, interval: int):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while self._running:
            services = registry.list_services()
            for svc in services:
                if svc.runtime_state not in ("running", "starting", "unhealthy"):
                    continue
                if not svc.service_url or not svc.health_endpoint:
                    continue
                
                try:
                    result = loop.run_until_complete(
                        self._probe(svc.service_url.rstrip("/") + "/" + svc.health_endpoint.lstrip("/"))
                    )
                    if result:
                        if svc.runtime_state != "running":
                            registry.set_runtime_state(svc.id, "running")
                    else:
                        if svc.runtime_state != "unhealthy":
                            registry.set_runtime_state(svc.id, "unhealthy")
                except Exception as e:
                    logger.debug("探测 %s 异常: %s", svc.id, e)
                    if svc.runtime_state != "unhealthy":
                        registry.set_runtime_state(svc.id, "unhealthy")
            
            # 等待指定间隔，但可被 stop() 中断
            for _ in range(interval):
                if not self._running:
                    break
                threading.Event().wait(1)
        
        loop.close()
    
    async def _probe(self, url: str) -> bool:
        """探测健康端点，5 秒超时，返回是否健康。"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status >= 200 and resp.status < 300
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False
```

### 健康探测规则

| 运行时状态 | 是否探测 | 探测返回 2xx | 探测返回非 2xx/超时 | 无 URL |
|-----------|---------|-------------|-------------------|--------|
| `stopped` | 否 | — | — | — |
| `starting` | 是 | → `running` | 保持 `starting` | — |
| `running` | 是 | 保持 `running` | → `unhealthy` | — |
| `unhealthy` | 是 | → `running` | 保持 `unhealthy` | — |
| `stopping` | 否 | — | — | — |
| `exited` | 否 | — | — | — |

URL 为空的服务（`service_url == ""`）跳过探测，状态由 ProcessManager 单独管理。

## 集成点

在 `main.py` 步骤 5-6 中：

```python
from core.process_manager import ProcessManager
from core.health_checker import HealthChecker

process_manager = ProcessManager()
process_manager.start_watcher()

health_checker = HealthChecker()
health_checker.start(interval_seconds=config.get_refresh_setting("health_check_seconds", 10))

# 步骤 6: auto-start
for svc in registry.list_services():
    if svc.enabled and svc.start_command:
        process_manager.start(svc.id)
```

## 验收标准

1. `ProcessManager.start("test")` 提交到队列后工作线程实际启动进程
2. 启动的进程 stdout/stderr 重定向到 `data/logs/services/test/<timestamp>.log`
3. `ProcessManager.stop("test")` 发送 SIGTERM，超时后 SIGKILL
4. `ProcessManager.restart("test")` 依次停止再启动
5. 监控线程检测到子进程退出后更新状态为 `exited`
6. `HealthChecker.start()` 每 N 秒探测一次运行中服务
7. 健康端点返回 2xx 时服务标记为 `running`
8. 健康端点不可达时服务标记为 `unhealthy`
9. 从 `unhealthy` 恢复为 `running` 时正确更新状态
10. `stop_all()` 在关闭时停止所有进程
