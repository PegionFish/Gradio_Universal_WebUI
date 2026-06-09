#!/usr/bin/env python3
"""Gradio 统一 AI WebUI — CLI 入口"""

import argparse
import sys
import os
import logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webui",
        description="Gradio Unified AI WebUI - One-stop frontend suite for managing local AI workloads",
    )
    parser.add_argument("--host", default=None, help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Listen port (default: 7860)")
    parser.add_argument("--config", default=None, help="Config directory (default: config/)")
    parser.add_argument("--log-level", default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Log level (default: INFO)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动序列 (8 步)。"""
    # 1. 解析 CLI 参数
    parser = build_parser()
    args = parser.parse_args(argv)

    # 2. 初始化日志系统
    from core.logging_setup import setup_logging

    config_dir = args.config or "config/"
    log_level = args.log_level or "INFO"

    # 尝试从配置文件读取日志设置（如果已存在）
    log_directory = "data/logs/"
    log_max_mb = 10
    log_backup_count = 5
    try:
        import yaml
        webui_path = os.path.join(config_dir, "webui.yaml")
        if os.path.exists(webui_path):
            with open(webui_path, "r", encoding="utf-8") as f:
                webui_cfg = yaml.safe_load(f) or {}
            log_cfg = webui_cfg.get("logging", {})
            log_level = args.log_level or log_cfg.get("level", "INFO")
            log_directory = log_cfg.get("directory", "data/logs/")
            log_max_mb = log_cfg.get("max_mb_per_file", 10)
            log_backup_count = log_cfg.get("backup_count", 5)
    except Exception:
        pass  # 使用默认值

    setup_logging(
        level=log_level,
        directory=log_directory,
        max_mb=log_max_mb,
        backup_count=log_backup_count,
    )
    logger.info("WebUI 启动 (host=%s, port=%s, config=%s)", args.host, args.port, config_dir)

    # 3. 初始化核心服务
    from core import setup_core
    setup_core(config_dir=config_dir)
    logger.info("核心服务已初始化")

    # 4. 加载配置并初始化 ServiceRegistry
    from core import config, registry
    try:
        config.load_all()
        services = config.get_services_list()
        registry.load_from_config(services)
        logger.info("配置已加载: %d 个服务", len(services))
    except Exception as e:
        logger.error("配置加载失败: %s", e)
        return 1

    # 5. 启动后台线程
    from core import process_manager, health_checker, registry, config
    process_manager.start_worker()
    process_manager.start_watcher()
    health_checker.start(
        interval_seconds=config.get_refresh_setting("health_check_seconds", 10)
    )
    # gpu_monitor.start()  (Module 7: GPU Monitor)
    logger.info("后台线程已启动 (ProcessManager, HealthChecker)")

    # 6. 自动启动 enabled 服务
    for svc in registry.list_services():
        if svc.enabled and svc.start_command:
            logger.info("自动启动服务: %s", svc.id)
            process_manager.start(svc.id)
    logger.info("Step 6: 自动启动服务完成")

    # 7. 构建并启动 WebUI
    #    (implemented in Module 9: WebUI Assembly)
    logger.info("Step 7: 构建 WebUI (pending Module 9)")

    # 8. 关闭清理
    logger.info("启动序列完成 (当前功能为桩实现)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())