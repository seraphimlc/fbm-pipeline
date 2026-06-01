#!/usr/bin/env python3
"""提交异步生图任务（使用curl避免代理问题）"""
import argparse
import json
import os
import subprocess
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
LOCAL_CONFIG_PATH = Path(__file__).parent / "config.local.json"

def load_config():
    config_path = LOCAL_CONFIG_PATH if LOCAL_CONFIG_PATH.exists() else CONFIG_PATH
    with open(config_path) as f:
        config = json.load(f)

    env_overrides = {
        "api_key": os.getenv("GPT_IMAGE_API_KEY"),
        "base_url": os.getenv("GPT_IMAGE_API_BASE"),
        "model": os.getenv("GPT_IMAGE_MODEL"),
        "default_size": os.getenv("GPT_IMAGE_DEFAULT_SIZE"),
    }
    for key, value in env_overrides.items():
        if value:
            config[key] = value

    if not config.get("api_key") or config.get("api_key") == "YOUR_API_KEY_HERE":
        raise RuntimeError(
            "Missing GPT image API key. Set GPT_IMAGE_API_KEY or create scripts/config.local.json."
        )
    return config

def adjust_size(size: str) -> str:
    """调整尺寸到16的倍数（向上取整）"""
    w, h = map(int, size.lower().split('x'))

    # 向上取整到16的倍数
    if w % 16 != 0:
        w = ((w // 16) + 1) * 16
    if h % 16 != 0:
        h = ((h // 16) + 1) * 16

    # 检查限制
    if max(w, h) > 3840:
        raise ValueError(f"尺寸超过限制：{w}x{h}，最大边长3840px")
    if max(w, h) / min(w, h) > 3:
        raise ValueError(f"长宽比超过限制：{w}x{h}，最大3:1")

    return f"{w}x{h}"

def generate(prompt: str, size: str = None, n: int = 1) -> dict:
    """提交生图任务，返回task_id"""
    config = load_config()

    if size is None:
        size = config.get("default_size", "2048x1152")

    size = adjust_size(size)

    # 使用curl避免代理问题
    cmd = [
        "curl", "-s", "-X", "POST",
        f"{config['base_url']}/v1/images/generations?async=true",
        "-H", f"Authorization: Bearer {config['api_key']}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({
            "prompt": prompt,
            "model": config["model"],
            "size": size,
            "n": n
        }),
        "--max-time", "60"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl失败: {result.stderr}")

    resp = json.loads(result.stdout)
    return {
        "task_id": resp.get("task_id"),
        "size": size,
        "prompt": prompt
    }

def main():
    parser = argparse.ArgumentParser(description="提交异步生图任务")
    parser.add_argument("--prompt", required=True, help="生图描述")
    parser.add_argument("--size", default=None, help="尺寸，如2048x1152")
    parser.add_argument("--n", type=int, default=1, help="数量")
    args = parser.parse_args()

    result = generate(args.prompt, args.size, args.n)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
