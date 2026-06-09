#!/usr/bin/env python3
"""Gradio 统一 AI WebUI — CLI 入口"""

import argparse
import sys
import os


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

    print(f"[WebUI] Startup parameters: host={args.host}, port={args.port}, config={args.config}, log_level={args.log_level}")

    # 2. Initialize logging system
    #    (implemented in Module 4: Logging System)
    print("[WebUI] Step 2: Initialize logging system (pending Module 4)")

    # 3. Initialize core services
    #    core.setup_core(config_dir=args.config or "config/")
    #    (create ConfigService, ServiceRegistry, ProcessManager instances)
    print("[WebUI] Step 3: Initialize core services (pending Module 3)")

    # 4. Load config and initialize ServiceRegistry
    #    (implemented in Module 2: Configuration System, Module 3: Service Registry & Event Bus)
    print("[WebUI] Step 4: Load config and initialize ServiceRegistry (pending Module 2,3)")

    # 5. Start background threads
    #    core.process_manager.start()           - worker thread
    #    core.process_manager.start_watcher()   - process monitoring
    #    health_checker.start()                 - health probing
    #    gpu_monitor.start()                    - GPU metrics collection
    #    (implemented in Module 5: Process Manager & Health Checker)
    #    (implemented in Module 7: GPU Monitor)
    print("[WebUI] Step 5: Start background threads (pending Module 5,7)")

    # 6. Auto-start enabled services
    #    (implemented in Module 5)
    print("[WebUI] Step 6: Auto-start enabled services (pending Module 5)")

    # 7. Build and launch WebUI
    #    (implemented in Module 9: WebUI Assembly)
    print("[WebUI] Step 7: Build and launch WebUI (pending Module 9)")

    # 8. Shutdown cleanup
    print("[WebUI] Startup sequence completed (all features are stubs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())