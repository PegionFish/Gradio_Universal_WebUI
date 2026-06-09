# core/logging_setup.py — 日志系统，统一管理日志输出、格式化和轮转

import logging
import logging.handlers
import os
import sys
import glob

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    directory: str = "data/logs/",
    max_mb: int = 10,
    backup_count: int = 5,
):
    """配置根日志记录器。应在进程启动早期调用，仅调用一次。

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        directory: 日志文件目录
        max_mb: 每个日志文件最大 MB，达到后轮转
        backup_count: 保留的轮转文件数
    """
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

    # 控制台处理器（Windows 兼容：替换不可编码字符）
    console_handler = logging.StreamHandler(
        sys.stdout if hasattr(sys.stdout, "buffer") else sys.stdout
    )
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    # 在 Windows cp1252 终端上，中文等字符会导致 UnicodeEncodeError。
    # 通过设置 stream 的 errors 为 'replace' 避免崩溃。
    if hasattr(sys.stdout, "buffer"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    root_logger.addHandler(console_handler)

    logging.getLogger(__name__).info(
        "日志系统已初始化 (level=%s, dir=%s, max_mb=%d, backups=%d)",
        level, directory, max_mb, backup_count,
    )


def tail_log(service_id: str, lines: int = 50, log_base_dir: str = "data/logs/services/") -> str:
    """返回服务日志的最后 N 行。

    Args:
        service_id: 服务 ID
        lines: 返回的行数
        log_base_dir: 服务日志根目录

    Returns:
        日志文件的最后 N 行文本，若无日志则返回 "(无日志)"
    """
    log_dir = os.path.join(log_base_dir, service_id)
    if not os.path.isdir(log_dir):
        return "(无日志)"

    log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")))
    if not log_files:
        return "(无日志)"

    latest = log_files[-1]
    try:
        with open(latest, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return "(日志读取失败)"

    return "".join(all_lines[-lines:])


def get_service_log_dir(service_id: str, log_base_dir: str = "data/logs/services/") -> str:
    """返回服务日志目录路径（必要时创建）。

    Args:
        service_id: 服务 ID
        log_base_dir: 服务日志根目录

    Returns:
        服务专属日志目录的绝对路径
    """
    log_dir = os.path.join(log_base_dir, service_id)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir
