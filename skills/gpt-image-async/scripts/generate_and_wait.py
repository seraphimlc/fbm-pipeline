#!/usr/bin/env python3
"""一键生图：提交 + 等待 + 下载（使用curl避免代理问题）"""
import argparse
import json
import time
import subprocess
from pathlib import Path
from generate import generate, load_config
from query import query

def download_image(url: str, output: str):
    """下载图片"""
    cmd = ["curl", "-sL", url, "-o", output]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"下载失败: {result.stderr}")
    return output

def generate_and_wait(prompt: str, size: str = None, n: int = 1,
                      output: str = None, timeout: int = 300) -> dict:
    """提交任务并等待完成"""
    # 提交任务
    task = generate(prompt, size, n)
    task_id = task["task_id"]
    print(f"✅ 任务已提交: {task_id}")
    print(f"   尺寸: {task['size']}")

    # 轮询查询
    start_time = time.time()
    while time.time() - start_time < timeout:
        result = query(task_id)
        status = result.get("data", {}).get("status", "UNKNOWN")

        if status == "SUCCESS":
            print(f"✅ 任务完成!")

            # 提取图片URL
            images = result.get("data", {}).get("data", {}).get("data", [])
            urls = [img.get("url") for img in images if img.get("url")]

            if not urls:
                return {"error": "任务成功但无图片URL", "result": result}

            # 下载图片
            if output:
                if len(urls) == 1:
                    download_image(urls[0], output)
                    print(f"✅ 图片已保存: {output}")
                else:
                    # 多张图片，添加序号
                    base = Path(output)
                    for i, url in enumerate(urls):
                        out_path = str(base.with_name(f"{base.stem}_{i+1}{base.suffix}"))
                        download_image(url, out_path)
                        print(f"✅ 图片{i+1}已保存: {out_path}")

            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "urls": urls,
                "output": output
            }

        elif status == "FAILURE":
            error = result.get("data", {}).get("fail_reason", "未知错误")
            print(f"❌ 任务失败: {error}")
            return {"error": error, "task_id": task_id}

        else:
            print(f"⏳ 等待中... ({status})")
            time.sleep(3)

    print(f"⏰ 超时（{timeout}秒）")
    return {"error": "超时", "task_id": task_id}

def main():
    parser = argparse.ArgumentParser(description="一键生图")
    parser.add_argument("--prompt", required=True, help="生图描述")
    parser.add_argument("--size", default=None, help="尺寸，如2048x1152")
    parser.add_argument("--n", type=int, default=1, help="数量")
    parser.add_argument("--output", default=None, help="输出路径")
    parser.add_argument("--timeout", type=int, default=300, help="超时时间（秒）")
    args = parser.parse_args()

    result = generate_and_wait(args.prompt, args.size, args.n, args.output, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()