#!/usr/bin/env python3
"""
Amazon Category Scraper - 从亚马逊商品页抓取类目信息
AppleScript + JS 控制航哥的 Chrome
"""

import subprocess
import json
import time
import sys
import os
import tempfile


def run_applescript(script: str, timeout: int = 15) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr}")
    return result.stdout.strip()


def scrape_category(asin: str, market: str = "com") -> dict:
    """抓取单个 ASIN 的类目信息"""
    domain = {"com": "www.amazon.com", "uk": "www.amazon.co.uk", "de": "www.amazon.de", "jp": "www.amazon.co.jp"}.get(market, "www.amazon.com")
    url = f"https://{domain}/dp/{asin}"

    # 打开页面
    run_applescript(f'''
tell application "Google Chrome"
    tell active tab of front window
        set URL to "{url}"
    end tell
end tell
''')
    time.sleep(4)

    # 提取面包屑 - 用临时文件存JS，避免引号转义地狱
    js_code = '''(function(){var bc=document.querySelector("#wayfinding-breadcrumbs_feature_div");return bc?bc.innerText.trim():null;})()'''
    
    js_file = os.path.join(tempfile.gettempdir(), "amazon_scrape_js.txt")
    with open(js_file, "w") as f:
        f.write(js_code)

    # 用 do shell script 读取JS代码，再执行
    raw = run_applescript(f'''
set jsCode to do shell script "cat {js_file}"
tell application "Google Chrome"
    tell active tab of front window
        execute javascript jsCode
    end tell
end tell
''')

    categories = []
    leaf = None
    if raw and raw != "missing value":
        categories = [c.strip() for c in raw.replace("\n", "").split("›") if c.strip()]
        leaf = categories[-1] if categories else None

    return {"asin": asin, "categories": categories, "leaf_category": leaf}


def main():
    asins = sys.argv[1:]
    if not asins:
        print("用法: python scrape_category.py B0GMWKDNBC [B0XXX ...]")
        sys.exit(1)

    for i, asin in enumerate(asins):
        try:
            result = scrape_category(asin)
            print(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"asin": asin, "error": str(e)}, ensure_ascii=False))
        if i < len(asins) - 1:
            time.sleep(4)


if __name__ == "__main__":
    main()
