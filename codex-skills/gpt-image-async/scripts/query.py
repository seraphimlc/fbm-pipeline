#!/usr/bin/env python3
"""查询异步生图任务状态（使用curl避免代理问题）"""
import argparse
import json
import subprocess
from config_loader import load_config


def query(task_id: str) -> dict:
    """查询任务状态"""
    config = load_config()

    cmd = [
        "curl", "-s", "-X", "GET",
        f"{config['base_url']}/v1/images/tasks/{task_id}",
        "-H", f"Authorization: Bearer {config['api_key']}",
        "-H", "Content-Type: application/json",
        "--max-time", "60"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl失败: {result.stderr}")

    return json.loads(result.stdout)

def main():
    parser = argparse.ArgumentParser(description="查询异步生图任务")
    parser.add_argument("--task_id", required=True, help="任务ID")
    args = parser.parse_args()

    result = query(args.task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
