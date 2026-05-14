"""
Chrome 控制器 — 通过 AppleScript 控制 Chrome 浏览器
提供串行锁，同一时间只允许一个 Chrome 操作
"""

import asyncio
import json
import subprocess
import logging
import os
import time
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)

# 全局Chrome串行锁
_chrome_lock = asyncio.Lock()


def _run_osascript(script: str, timeout: int = 30) -> tuple[str, str]:
    """执行 AppleScript，返回 (stdout, stderr)"""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip()


def _write_js_file(name: str, js_code: str) -> str:
    """将 JS 代码写入临时文件，返回文件路径"""
    path = f"/tmp/fbm_{name}.js"
    with open(path, "w") as f:
        f.write(js_code)
    return path


async def chrome_navigate(url: str, wait: float = 3.0) -> bool:
    """在 Chrome 当前标签页打开 URL"""
    async with _chrome_lock:
        script = f'''tell application "Google Chrome"
    tell active tab of front window
        set URL to "{url}"
    end tell
end tell'''
        try:
            _run_osascript(script)
            await asyncio.sleep(wait)
            return True
        except Exception as e:
            logger.error(f"Chrome导航失败: {e}")
            return False


async def chrome_execute_js(js_code: str, timeout: int = 30) -> str | None:
    """在 Chrome 当前标签页执行 JS 并返回结果"""
    async with _chrome_lock:
        # 写入临时文件
        js_path = _write_js_file("exec", js_code)
        script = f'''tell application "Google Chrome"
    tell active tab of front window
        set jsFile to do shell script "cat {js_path}"
        set result to execute javascript jsFile
        return result
    end tell
end tell'''
        try:
            stdout, stderr = _run_osascript(script, timeout)
            if stderr and "error" in stderr.lower():
                logger.error(f"Chrome JS执行错误: {stderr}")
                return None
            return stdout
        except Exception as e:
            logger.error(f"Chrome JS执行失败: {e}")
            return None


async def chrome_get_page_info() -> dict | None:
    """获取当前页面基本信息（URL, title）"""
    async with _chrome_lock:
        script = '''tell application "Google Chrome"
    tell active tab of front window
        return URL & "|||" & title
    end tell
end tell'''
        try:
            stdout, _ = _run_osascript(script)
            if "|||" in stdout:
                url, title = stdout.split("|||", 1)
                return {"url": url, "title": title}
            return None
        except Exception as e:
            logger.error(f"获取页面信息失败: {e}")
            return None


async def chrome_click_element(selector: str, wait: float = 1.0) -> bool:
    """通过 JS 点击指定选择器的元素"""
    js = f'''(function() {{
    var el = document.querySelector('{selector}');
    if (el) {{ el.click(); return 'clicked'; }}
    return 'not_found';
}})()'''
    result = await chrome_execute_js(js)
    if result == "clicked":
        await asyncio.sleep(wait)
        return True
    return False
