# 模块 4：日志系统

## 用途

统一管理 WebUI 核心组件和托管的模型服务进程的日志输出、格式化和轮转。

## 依赖

- **模块 1**：项目骨架（日志写入 `data/logs/`）

## 日志文件结构

```
data/logs/
├── webui.log                    # WebUI 应用日志（用户操作、UI 事件）
├── core.log                     # 核心服务日志（ConfigService, ProcessManager, 等）
├── gpu.log                      # GPU 监控日志（NVML 状态、推荐事件）
└── services/
    └── <service_id>/
        └── <start_timestamp>.log  # 托管进程的 stdout/stderr
```

## 配置

日志配置来自 `config/webui.yaml` 的 `logging` 段：

```yaml
logging:
  level: "INFO"          # DEBUG | INFO | WARNING | ERROR
  max_mb_per_file: 10    # 每个日志文件最大 MB，达到后轮转
  backup_count: 5        # 保留的轮转文件数
  directory: "data/logs/"
```

## 初始化函数

```python
import logging
import logging.handlers
import os
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    directory: str = "data/logs/",
    max_mb: int = 10,
    backup_count: int = 5,
):
    """配置根日志记录器。应在进程启动早期调用，仅调用一次。"""
    os.makedirs(directory, exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # 清除已有处理器（防止多次初始化）
    root_logger.handlers.clear()
    
    # 文件处理器（自动轮转）
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(directory, "webui.log"),
        maxBytes=max_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(file_handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(console_handler)
```

## 获取日志器

各模块通过 `logging.getLogger(__name__)` 获取自己的日志器：

```python
# core/process_manager.py
logger = logging.getLogger("core.process_manager")
logger.info("已启动服务 %s (进程 PID %d)", service_id, pid)

# core/health_checker.py
logger = logging.getLogger("core.health_checker")
logger.warning("服务 %s 不健康: 连接被拒绝", service_id)

# adapters/stable_diffusion.py
logger = logging.getLogger("adapters.stable_diffusion")
logger.error("占位适配器的 submit 被调用——未实现")
```

日志器名称使用点分隔层级：`core.*`、`webui.*`、`adapters.*`。

## 服务日志捕获

`ProcessManager` 启动托管进程时，将 stdout/stderr 写入服务专属日志文件：

```python
def _open_service_log(self, service_id: str) -> str:
    """创建服务日志文件并返回路径。"""
    log_dir = os.path.join("data/logs/services", service_id)
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{timestamp}.log")
    return log_path


def start(self, service_id: str):
    service = registry.get(service_id)
    log_path = self._open_service_log(service_id)
    log_file = open(log_path, "w", encoding="utf-8")
    
    process = subprocess.Popen(
        service.start_command,
        shell=True,
        cwd=service.working_dir,
        env=env,
        stdout=log_file,
        stderr=log_file,
        preexec_fn=os.setsid,
    )
    
    # 记录进程信息和日志路径
    self._log_files[service_id] = log_path
```

## 服务日志查看

WebUI 服务管理页面通过读取日志文件的末尾 N 行来展示：

```python
def tail_log(service_id: str, lines: int = 50) -> str:
    """返回服务日志的最后 N 行。"""
    import glob
    log_dir = os.path.join("data/logs/services", service_id)
    log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")))
    if not log_files:
        return "(无日志)"
    
    latest = log_files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])
```

## 集成点

在 `main.py` 步骤 2 中调用：

```python
from core.logging_setup import setup_logging

# 从配置读取日志设置
log_cfg = config.get_webui_config().get("logging", {})
setup_logging(
    level=args.log_level or log_cfg.get("level", "INFO"),
    directory=log_cfg.get("directory", "data/logs/"),
    max_mb=log_cfg.get("max_mb_per_file", 10),
    backup_count=log_cfg.get("backup_count", 5),
)
```

## 验收标准

1. 调用 `setup_logging()` 后 `logging.getLogger("core.test").info("msg")` 写入 `data/logs/webui.log`
2. 日志文件达到 `max_mb` 后自动轮转，旧文件后缀 `.1`, `.2`...
3. 服务日志独立写入 `data/logs/services/<id>/<timestamp>.log`
4. `tail_log()` 返回正确的最后 N 行
5. 日志格式符合 `2026-06-08 10:15:30 [INFO] [core.xxx] 消息`
6. Windows 下日志文件使用 UTF-8 编码（open 时指定 `encoding="utf-8"`）
