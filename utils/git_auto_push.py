#!/usr/bin/env python3
"""自动提交和推送到GitHub的脚本"""

import subprocess
import datetime
import sys
import os


def commit_and_push(session_name: str) -> None:
    """自动提交和推送到GitHub"""
    try:
        # 构造提交消息
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"[{timestamp}] {session_name}"

        print(f"Preparing commit: {commit_msg}")

        # Get current git status
        status_result = subprocess.run(["git", "status", "--porcelain"],
                                      capture_output=True, text=True, check=False)

        if not status_result.stdout.strip():
            print("No changes to commit")
            return

        # Show status changes
        print("Detected changes:")
        for line in status_result.stdout.strip().split('\n'):
            if line:
                print(f"  {line}")

        # Add all changes
        print("Adding all changes...")
        subprocess.run(["git", "add", "."], check=True)

        # Commit
        print(f"Committing: {commit_msg}")
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)

        # Push to remote
        print("Pushing to remote repository...")
        subprocess.run(["git", "push", "origin", "main"], check=True)

        print(f"✓ Successfully committed and pushed: {commit_msg}")

    except subprocess.CalledProcessError as e:
        print(f"✗ Git operation failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unknown error: {e}")
        sys.exit(1)


def get_current_branch() -> str:
    """获取当前分支"""
    try:
        result = subprocess.run(["git", "branch", "--show-current"],
                               capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


if __name__ == "__main__":
    # Ensure at project root
    if not os.path.exists(".git"):
        print("Error: Not in git repository root directory")
        sys.exit(1)

    if len(sys.argv) < 2:
        session_name = "Update"
    else:
        session_name = " ".join(sys.argv[1:])

    current_branch = get_current_branch()
    print(f"Current branch: {current_branch}")

    confirm = input(f"Confirm commit to remote branch '{current_branch}'? (y/N): ")
    if confirm.lower() == 'y':
        commit_and_push(session_name)
    else:
        print("Commit cancelled")