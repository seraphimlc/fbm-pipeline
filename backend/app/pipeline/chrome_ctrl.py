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
from contextlib import asynccontextmanager
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)

# 全局Chrome串行锁
_chrome_lock = asyncio.Lock()

# 全局浏览器流程并发控制。
# _chrome_lock 只保护一次 AppleScript/JS 动作；这个锁保护一整段
# “打开页面 -> 等待 -> 执行JS/点击/下载”的业务流程，避免并发任务串页。
_browser_workflow_semaphore = asyncio.Semaphore(max(1, settings.BROWSER_WORKFLOW_CONCURRENCY))

# 专用标签页标记。所有采集/类目操作都在这个 tab 里执行，不抢用户当前页面。
FBM_TAB_MARKER = "#fbm-pipeline-worker"
FBM_TAB_ID_FILE = Path("/tmp/fbm_pipeline_chrome_tab_id")


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


def _read_worker_tab_id() -> str:
    try:
        return FBM_TAB_ID_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


def _write_worker_tab_id(tab_id: str) -> None:
    if tab_id:
        FBM_TAB_ID_FILE.write_text(str(tab_id))


@asynccontextmanager
async def chrome_workflow(name: str):
    """串行化一整段浏览器业务流程，避免多个任务共用 worker tab 时互相覆盖页面。"""
    if _browser_workflow_semaphore.locked():
        logger.info(
            f"[ChromeWorkflow] 等待浏览器流程名额: {name}, "
            f"concurrency={settings.BROWSER_WORKFLOW_CONCURRENCY}"
        )
    started_at = time.monotonic()
    async with _browser_workflow_semaphore:
        waited = time.monotonic() - started_at
        if waited >= 1:
            logger.info(f"[ChromeWorkflow] 已获取浏览器流程名额: {name}, waited={waited:.1f}s")
        try:
            yield
        finally:
            logger.info(f"[ChromeWorkflow] 释放浏览器流程名额: {name}")


async def chrome_navigate(url: str, wait: float = 3.0) -> bool:
    """在 Chrome 专用标签页打开 URL，不切换用户当前标签页。"""
    async with _chrome_lock:
        worker_tab_id = _read_worker_tab_id()
        script = f'''tell application "Google Chrome"
    if (count of windows) = 0 then make new window
    set workerTab to missing value
    set workerTabId to "{worker_tab_id}"
    if workerTabId is not "" then
        repeat with w in windows
            repeat with t in tabs of w
                if ((id of t) as string) is workerTabId then
                    set workerTab to t
                    exit repeat
                end if
            end repeat
            if workerTab is not missing value then exit repeat
        end repeat
    end if
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t contains "{FBM_TAB_MARKER}") then
                set workerTab to t
                exit repeat
            end if
        end repeat
        if workerTab is not missing value then exit repeat
    end repeat
    if workerTab is missing value then
        set workerTab to make new tab at end of tabs of front window
    end if
    tell workerTab
        set URL to "{url}"
        return ((id of workerTab) as string)
    end tell
end tell'''
        try:
            stdout, stderr = _run_osascript(script)
            if stderr and "error" in stderr.lower():
                logger.error(f"Chrome导航错误: {stderr}")
                return False
            _write_worker_tab_id(stdout)
            await asyncio.sleep(wait)
            return True
        except Exception as e:
            logger.error(f"Chrome导航失败: {e}")
            return False


async def chrome_open_url_for_user(url: str, wait: float = 1.0) -> bool:
    """在用户可见的 Chrome 前台标签页打开 URL，适合人工登录/授权。"""
    async with _chrome_lock:
        script = f'''tell application "Google Chrome"
    activate
    if (count of windows) = 0 then make new window
    tell front window
        set userTab to make new tab at end of tabs
        set active tab index to (count of tabs)
        set URL of userTab to "{url}"
    end tell
    return "ok"
end tell'''
        try:
            stdout, stderr = _run_osascript(script)
            if stderr and "error" in stderr.lower():
                logger.error(f"Chrome打开人工页面错误: {stderr}")
                return False
            await asyncio.sleep(wait)
            return stdout == "ok"
        except Exception as e:
            logger.error(f"Chrome打开人工页面失败: {e}")
            return False


async def chrome_execute_js(js_code: str, timeout: int = 30) -> str | None:
    """在 Chrome 专用标签页执行 JS 并返回结果"""
    async with _chrome_lock:
        # 写入临时文件
        js_path = _write_js_file("exec", js_code)
        worker_tab_id = _read_worker_tab_id()
        script = f'''tell application "Google Chrome"
    set workerTab to missing value
    set workerTabId to "{worker_tab_id}"
    if workerTabId is not "" then
        repeat with w in windows
            repeat with t in tabs of w
                if ((id of t) as string) is workerTabId then
                    set workerTab to t
                    exit repeat
                end if
            end repeat
            if workerTab is not missing value then exit repeat
        end repeat
    end if
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t contains "{FBM_TAB_MARKER}") then
                set workerTab to t
                exit repeat
            end if
        end repeat
        if workerTab is not missing value then exit repeat
    end repeat
    if workerTab is missing value then error "FBM Pipeline worker tab not found"
    tell workerTab
        set jsFile to do shell script "cat " & quoted form of "{js_path}"
        set jsResult to execute javascript jsFile
        return jsResult
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
    """获取 Chrome 专用标签页基本信息（URL, title）"""
    async with _chrome_lock:
        worker_tab_id = _read_worker_tab_id()
        script = f'''tell application "Google Chrome"
    set workerTab to missing value
    set workerTabId to "{worker_tab_id}"
    if workerTabId is not "" then
        repeat with w in windows
            repeat with t in tabs of w
                if ((id of t) as string) is workerTabId then
                    set workerTab to t
                    exit repeat
                end if
            end repeat
            if workerTab is not missing value then exit repeat
        end repeat
    end if
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t contains "#fbm-pipeline-worker") then
                set workerTab to t
                exit repeat
            end if
        end repeat
        if workerTab is not missing value then exit repeat
    end repeat
    if workerTab is missing value then return ""
    tell workerTab
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


async def chrome_get_cookie_for_domain(domain: str) -> str | None:
    """从已打开的 Chrome 标签页里找指定域名并读取 cookie，不切换当前页面。"""
    async with _chrome_lock:
        script = f'''tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t contains "{domain}") then
                tell t
                    return execute javascript "document.cookie"
                end tell
            end if
        end repeat
    end repeat
    return ""
end tell'''
        try:
            stdout, stderr = _run_osascript(script)
            if stderr and "error" in stderr.lower():
                logger.error(f"Chrome Cookie读取错误: {stderr}")
                return None
            return stdout or None
        except Exception as e:
            logger.error(f"Chrome Cookie读取失败: {e}")
            return None
