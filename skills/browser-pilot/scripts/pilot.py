#!/usr/bin/env python3
"""Browser Pilot — 万能浏览器操作框架

渐进式自动化：API直连 > DOM操作 > 多模态点击
成功操作自动固化到缓存，越用越快。

Commands:
  list           列出所有已配置的操作
  run            执行操作（自动选择最快路径）
  explore        交互式探索新操作
  cache          缓存管理（status/update/clear）
  history        查看操作执行历史
  chrome         Chrome控制（open/info/cookie/js/screenshot）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 路径配置
SKILL_DIR = Path(__file__).parent.parent
ACTIONS_DIR = SKILL_DIR / "references" / "actions"
CACHE_DIR = SKILL_DIR / "references" / "cache"
HISTORY_FILE = SKILL_DIR / "references" / "history.jsonl"

# 确保目录存在
ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Chrome 控制层
# ============================================================

class ChromeController:
    """通过AppleScript控制本地Chrome浏览器"""

    @staticmethod
    def open_url(url):
        """在Chrome当前标签页打开URL"""
        script = f'''
tell application "Google Chrome"
    activate
    if (count of windows) = 0 then
        make new window
    end if
    tell active tab of front window
        set URL to "{url}"
    end tell
end tell
'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return result.returncode == 0

    @staticmethod
    def get_page_info():
        """获取当前页面标题和URL"""
        script = '''
tell application "Google Chrome"
    tell active tab of front window
        return {title, URL}
    end tell
end tell
'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split(", ")
        if len(parts) >= 2:
            return {"title": parts[0], "url": parts[1]}
        return None

    @staticmethod
    def get_cookie():
        """从Chrome当前页面获取Cookie"""
        script = '''
tell application "Google Chrome"
    tell active tab of front window
        return execute javascript "document.cookie"
    end tell
end tell
'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if result.returncode != 0 or result.stdout.strip() == "missing value":
            return None
        return result.stdout.strip()

    @staticmethod
    def execute_js(js_code):
        """在Chrome当前页面执行JavaScript"""
        # 转义JS代码中的双引号
        escaped = js_code.replace('\\', '\\\\').replace('"', '\\"')
        script = f'''
tell application "Google Chrome"
    tell active tab of front window
        return execute javascript "{escaped}"
    end tell
end tell
'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        if result.returncode != 0 or result.stdout.strip() == "missing value":
            return None
        return result.stdout.strip()

    @staticmethod
    def screenshot(output_path="/tmp/browser_pilot_screenshot.png"):
        """截取屏幕"""
        subprocess.run(["screencapture", "-x", output_path], timeout=5)
        return output_path

    @staticmethod
    def click_at(x, y):
        """模拟鼠标点击指定坐标"""
        result = subprocess.run(["cliclick", f"c:{x},{y}"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0


# ============================================================
# DOM 操作层
# ============================================================

class DOMOperator:
    """DOM查找+点击，选择器多层降级"""

    @staticmethod
    def find_and_click(selectors, chrome=None):
        """按优先级尝试多种选择器方式点击

        Args:
            selectors: 选择器列表，按优先级排列
                [{"type": "css", "value": "..."}, {"type": "text", "value": "导出"}, ...]
            chrome: ChromeController实例（可选，默认新建）

        Returns:
            dict: {success, method, detail}
        """
        if chrome is None:
            chrome = ChromeController()

        for sel in selectors:
            sel_type = sel.get("type", "css")
            sel_value = sel.get("value", "")
            exclude = sel.get("exclude", "")

            if sel_type == "css":
                result = DOMOperator._click_by_css(sel_value, chrome)
            elif sel_type == "text":
                result = DOMOperator._click_by_text(sel_value, exclude, chrome)
            elif sel_type == "aria":
                result = DOMOperator._click_by_aria(sel_value, chrome)
            else:
                continue

            if result.get("found"):
                return {"success": True, "method": sel_type, "detail": result}

        return {"success": False, "method": None, "detail": "所有选择器均未找到元素"}

    @staticmethod
    def _click_by_css(selector, chrome):
        js = f'''
(function() {{
    var el = document.querySelector("{selector}");
    if (el) {{
        el.click();
        return JSON.stringify({{found: true, tag: el.tagName, text: el.innerText.trim().substring(0, 50)}});
    }}
    return JSON.stringify({{found: false}});
}})()
'''
        result = chrome.execute_js(js)
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return {"found": False}

    @staticmethod
    def _click_by_text(target_text, exclude_text, chrome):
        escaped_target = target_text.replace("'", "\\'")
        escaped_exclude = exclude_text.replace("'", "\\'") if exclude_text else ""
        js = f'''
(function() {{
    var target = "{escaped_target}";
    var exclude = "{escaped_exclude}";
    var elements = document.querySelectorAll("button, a, [role='button'], [onclick], span[onclick]");
    for (var i = 0; i < elements.length; i++) {{
        var text = elements[i].innerText.trim();
        if (text === target || text.includes(target)) {{
            if (exclude && text.includes(exclude)) continue;
            if (elements[i].disabled) continue;
            elements[i].click();
            return JSON.stringify({{found: true, tag: elements[i].tagName, text: text}});
        }}
    }}
    return JSON.stringify({{found: false}});
}})()
'''
        result = chrome.execute_js(js)
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return {"found": False}

    @staticmethod
    def _click_by_aria(label, chrome):
        escaped = label.replace("'", "\\'")
        js = f'''
(function() {{
    var el = document.querySelector("[aria-label*='" + "{escaped}" + "']");
    if (el) {{
        el.click();
        return JSON.stringify({{found: true, tag: el.tagName}});
    }}
    return JSON.stringify({{found: false}});
}})()
'''
        result = chrome.execute_js(js)
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return {"found": False}

    @staticmethod
    def enumerate_buttons(chrome=None):
        """枚举页面上所有可见按钮（调试用）"""
        if chrome is None:
            chrome = ChromeController()
        js = '''
(function() {
    var btns = document.querySelectorAll("button, a, [role='button']");
    var result = [];
    for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        if (b.offsetParent === null) continue;
        result.push({
            index: i,
            text: b.innerText.trim().substring(0, 50),
            className: b.className.substring(0, 80),
            tag: b.tagName,
            disabled: b.disabled,
            ariaLabel: b.getAttribute("aria-label") || ""
        });
    }
    return JSON.stringify(result.slice(0, 30));
})()
'''
        result = chrome.execute_js(js)
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return []


# ============================================================
# API 直连层
# ============================================================

class APICaller:
    """直接HTTP请求，0浏览器交互"""

    @staticmethod
    def call(url, cookie_str, method="GET", data=None, headers=None, output_path=None):
        """发送HTTP请求

        Args:
            url: 完整URL
            cookie_str: Cookie字符串
            method: GET/POST
            data: 请求体（dict，自动转JSON）
            headers: 额外headers
            output_path: 如果提供，响应保存到文件

        Returns:
            dict: {success, status_code, body, path}
        """
        cmd = ["curl", "-s", "-w", "\n%{http_code}"]

        if method == "POST":
            cmd.extend(["-X", "POST"])

        cmd.extend(["-H", f"Cookie: {cookie_str}"])

        default_headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "*/*",
        }
        if headers:
            default_headers.update(headers)

        for k, v in default_headers.items():
            cmd.extend(["-H", f"{k}: {v}"])

        if data:
            cmd.extend(["-d", json.dumps(data)])

        if output_path:
            cmd.extend(["-o", output_path])

        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            output = result.stdout.decode("utf-8", errors="replace")

            if output_path:
                # curl -o 模式，状态码在stderr的-w里
                # 重新获取状态码
                status_cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}"]
                if method == "POST":
                    status_cmd.extend(["-X", "POST"])
                status_cmd.extend(["-H", f"Cookie: {cookie_str}"])
                for k, v in default_headers.items():
                    status_cmd.extend(["-H", f"{k}: {v}"])
                if data:
                    status_cmd.extend(["-d", json.dumps(data)])
                status_cmd.append(url)
                status_result = subprocess.run(status_cmd, capture_output=True, timeout=60)
                status_code = int(status_result.stdout.decode().strip()) if status_result.stdout else 0
            else:
                parts = output.rsplit("\n", 1)
                if len(parts) == 2 and parts[1].strip().isdigit():
                    status_code = int(parts[1].strip())
                    body = parts[0]
                else:
                    status_code = 0
                    body = output

            return {
                "success": 200 <= status_code < 300,
                "status_code": status_code,
                "path": output_path
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "status_code": 0, "error": "timeout"}
        except Exception as e:
            return {"success": False, "status_code": 0, "error": str(e)}


# ============================================================
# 操作配置管理
# ============================================================

class ActionManager:
    """管理操作配置文件"""

    @staticmethod
    def list_actions():
        """列出所有已配置的操作"""
        actions = []
        for f in ACTIONS_DIR.glob("*.json"):
            try:
                with open(f) as fh:
                    cfg = json.load(fh)
                actions.append({
                    "id": cfg.get("id", f.stem),
                    "name": cfg.get("name", ""),
                    "site": cfg.get("site", ""),
                    "fallback_order": cfg.get("fallback_order", []),
                    "last_used_layer": cfg.get("last_used_layer", ""),
                    "last_success_date": cfg.get("last_success_date", "")
                })
            except Exception:
                actions.append({"id": f.stem, "name": "⚠️ 配置文件损坏"})
        return actions

    @staticmethod
    def load_action(action_id):
        """加载操作配置"""
        path = ACTIONS_DIR / f"{action_id}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    @staticmethod
    def save_action(action_id, config):
        """保存操作配置"""
        path = ACTIONS_DIR / f"{action_id}.json"
        with open(path, "w") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def update_cache(action_id, layer, success=True):
        """更新操作的缓存状态"""
        config = ActionManager.load_action(action_id)
        if not config:
            return
        if success:
            config["last_used_layer"] = layer
            config["last_success_date"] = datetime.now().strftime("%Y-%m-%d")
        ActionManager.save_action(action_id, config)

    @staticmethod
    def log_history(action_id, layer, success, params=None, detail=None):
        """记录操作历史"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action_id": action_id,
            "layer": layer,
            "success": success,
            "params": params or {},
            "detail": detail or ""
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================
# 核心：执行引擎
# ============================================================

class PilotEngine:
    """渐进式执行引擎"""

    def __init__(self):
        self.chrome = ChromeController()
        self.dom = DOMOperator()
        self.api = APICaller()

    def run(self, action_id, params=None, force_layer=None):
        """执行操作，自动选择最快路径

        Args:
            action_id: 操作ID
            params: 参数dict，如 {"ASIN": "B0GMWKDNBC"}
            force_layer: 强制使用指定层（api/page/multimodal）

        Returns:
            dict: {success, layer, detail}
        """
        config = ActionManager.load_action(action_id)
        if not config:
            return {"success": False, "layer": None, "detail": f"操作未配置: {action_id}"}

        params = params or {}
        fallback_order = force_layer if force_layer else config.get("fallback_order", ["api", "page", "multimodal"])
        if isinstance(fallback_order, str):
            fallback_order = [fallback_order]

        # 替换模板参数
        resolved = self._resolve_templates(config, params)

        for layer in fallback_order:
            print(f"🔄 尝试第{['API直连','DOM操作','多模态'][['api','page','multimodal'].index(layer)]}层: {layer}")

            if layer == "api":
                result = self._run_api(resolved, params)
            elif layer == "page":
                result = self._run_page(resolved, params)
            elif layer == "multimodal":
                result = self._run_multimodal(resolved, params)
            else:
                continue

            ActionManager.log_history(action_id, layer, result["success"], params, str(result.get("detail", "")))

            if result["success"]:
                ActionManager.update_cache(action_id, layer, success=True)
                print(f"✅ 成功（{layer}层）")
                return result

            print(f"❌ {layer}层失败: {result.get('detail', '')}")

        return {"success": False, "layer": None, "detail": "所有层均失败"}

    def _resolve_templates(self, config, params):
        """替换配置中的模板变量 {KEY} → 实际值"""
        config_str = json.dumps(config)
        for key, value in params.items():
            config_str = config_str.replace(f"{{{key}}}", str(value))
        return json.loads(config_str)

    def _run_api(self, config, params):
        """第1层：API直连"""
        api_cfg = config.get("layers", {}).get("api")
        if not api_cfg:
            return {"success": False, "layer": "api", "detail": "未配置API层"}

        # 获取Cookie
        cookie = self.chrome.get_cookie()
        if not cookie:
            return {"success": False, "layer": "api", "detail": "无法获取Cookie"}

        # 检查必需Cookie
        required = config.get("auth", {}).get("required_cookies", [])
        for rc in required:
            if rc not in cookie:
                return {"success": False, "layer": "api", "detail": f"缺少必需Cookie: {rc}"}

        # 构造URL（拼接params到query string）
        base_url = api_cfg.get("url", "")
        api_params = api_cfg.get("params", {})
        if api_params:
            query = "&".join(f"{k}={v}" for k, v in api_params.items())
            url = f"{base_url}?{query}" if "?" not in base_url else f"{base_url}&{query}"
        else:
            url = base_url

        method = api_cfg.get("method", "GET")
        body = api_cfg.get("body_template")
        headers = api_cfg.get("headers", {})
        output_path = None

        # 如果响应是blob，保存到文件
        if api_cfg.get("response_type") == "blob":
            output_dir = Path("~/Documents/F/亚马逊工作目录/亚马逊商品").expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            asin = params.get("ASIN", "unknown")
            output_path = str(output_dir / f"ReverseASIN-US-{asin}-Keywords.xlsx")

        result = self.api.call(url, cookie, method=method, data=body, headers=headers, output_path=output_path)

        # 校验
        verify = api_cfg.get("verify", {})
        if result["success"] and verify:
            if verify.get("http_status") and result.get("status_code") != verify["http_status"]:
                result["success"] = False

        return {"success": result["success"], "layer": "api", "detail": result}

    def _run_page(self, config, params):
        """第2层：URL直连 + DOM操作"""
        page_cfg = config.get("layers", {}).get("page")
        if not page_cfg:
            return {"success": False, "layer": "page", "detail": "未配置Page层"}

        steps = page_cfg.get("steps", [])
        for i, step in enumerate(steps):
            action = step.get("action")

            if action == "navigate":
                url = step.get("url_template", step.get("url", ""))
                if not self.chrome.open_url(url):
                    return {"success": False, "layer": "page", "detail": f"Step {i}: 打开URL失败"}
                time.sleep(3)

            elif action == "click":
                selectors = step.get("selectors", [])
                result = self.dom.find_and_click(selectors, self.chrome)
                if not result["success"]:
                    return {"success": False, "layer": "page", "detail": f"Step {i}: 点击失败 - {result['detail']}"}
                time.sleep(1)

            elif action == "wait":
                time.sleep(step.get("seconds", 2))

        return {"success": True, "layer": "page", "detail": "所有步骤完成"}

    def _run_multimodal(self, config, params):
        """第3层：多模态操作（需要Agent配合，此处只提供基础设施）"""
        # 多模态操作需要Agent的image工具和判断能力
        # 这里只提供截屏和点击的基础能力
        screenshot_path = self.chrome.screenshot()
        return {
            "success": False,
            "layer": "multimodal",
            "detail": "多模态操作需要Agent配合，请使用截屏+VLM识别",
            "screenshot": screenshot_path
        }


# ============================================================
# CLI 入口
# ============================================================

def cmd_list(args):
    actions = ActionManager.list_actions()
    if not actions:
        print("📭 暂无已配置的操作")
        return
    for a in actions:
        layer = a.get("last_used_layer", "未使用")
        date = a.get("last_success_date", "-")
        print(f"  {a['id']:<40} {a.get('name', ''):<20} 最快层: {layer}  上次: {date}")


def cmd_run(args):
    engine = PilotEngine()
    result = engine.run(args.action_id, params=json.loads(args.params) if args.params else {}, force_layer=args.layer)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def cmd_explore(args):
    chrome = ChromeController()
    print(f"🌐 打开: {args.url}")
    chrome.open_url(args.url)
    time.sleep(3)

    info = chrome.get_page_info()
    print(f"📄 页面: {info}")

    buttons = DOMOperator.enumerate_buttons(chrome)
    print(f"\n🔘 发现 {len(buttons)} 个按钮:")
    for b in buttons:
        disabled = " [禁用]" if b.get("disabled") else ""
        print(f"  [{b['index']}] <{b['tag']}> {b['text']}{disabled}")
        if b.get("className"):
            print(f"       class: {b['className'][:60]}")
        if b.get("ariaLabel"):
            print(f"       aria: {b['ariaLabel']}")

    if args.action:
        print(f"\n🎯 尝试操作: {args.action}")


def cmd_cache(args):
    if args.cache_action == "status":
        actions = ActionManager.list_actions()
        for a in actions:
            print(f"  {a['id']}: last_layer={a.get('last_used_layer', '-')}, date={a.get('last_success_date', '-')}")
    elif args.cache_action == "clear":
        config = ActionManager.load_action(args.action_id)
        if config:
            config["last_used_layer"] = ""
            config["last_success_date"] = ""
            ActionManager.save_action(args.action_id, config)
            print(f"✅ 已清除 {args.action_id} 的缓存")
        else:
            print(f"❌ 未找到操作: {args.action_id}")
    elif args.cache_action == "update":
        if not args.action_id or not args.layer:
            print("❌ 需要 --action-id 和 --layer")
            return
        ActionManager.update_cache(args.action_id, args.layer, success=True)
        print(f"✅ 已更新 {args.action_id} 的最快层为 {args.layer}")


def cmd_history(args):
    if not HISTORY_FILE.exists():
        print("📭 暂无历史记录")
        return
    with open(HISTORY_FILE) as f:
        lines = f.readlines()
    lines = lines[-(args.limit or 20):]
    for line in lines:
        try:
            entry = json.loads(line)
            status = "✅" if entry["success"] else "❌"
            print(f"  {entry['timestamp'][:19]} {status} {entry['action_id']} [{entry['layer']}] {entry.get('detail', '')[:60]}")
        except json.JSONDecodeError:
            pass


def cmd_chrome(args):
    chrome = ChromeController()
    if args.chrome_action == "open":
        chrome.open_url(args.url)
        print(f"✅ 已打开: {args.url}")
    elif args.chrome_action == "info":
        info = chrome.get_page_info()
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif args.chrome_action == "cookie":
        cookie = chrome.get_cookie()
        if cookie:
            has_token = "Sprite-X-Token" in cookie if cookie else False
            print(f"Cookie长度: {len(cookie)}, 含Token: {has_token}")
        else:
            print("❌ 无法获取Cookie")
    elif args.chrome_action == "js":
        result = chrome.execute_js(args.js_code)
        print(result or "(无返回值)")
    elif args.chrome_action == "screenshot":
        path = chrome.screenshot(args.output or "/tmp/browser_pilot_screenshot.png")
        print(f"📸 截屏保存: {path}")
    elif args.chrome_action == "buttons":
        buttons = DOMOperator.enumerate_buttons(chrome)
        print(json.dumps(buttons, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Browser Pilot — 万能浏览器操作框架")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # list
    sub.add_parser("list", help="列出所有已配置的操作")

    # run
    p = sub.add_parser("run", help="执行操作")
    p.add_argument("action_id", help="操作ID")
    p.add_argument("--params", help="参数JSON，如 '{\"ASIN\": \"B0GMWKDNBC\"}'")
    p.add_argument("--layer", help="强制使用指定层 (api/page/multimodal)")

    # explore
    p = sub.add_parser("explore", help="交互式探索")
    p.add_argument("--url", required=True, help="目标URL")
    p.add_argument("--action", help="要执行的操作描述")

    # cache
    p = sub.add_parser("cache", help="缓存管理")
    p.add_argument("cache_action", choices=["status", "clear", "update"])
    p.add_argument("--action-id", help="操作ID")
    p.add_argument("--layer", help="层名称")

    # history
    p = sub.add_parser("history", help="操作历史")
    p.add_argument("--limit", type=int, default=20)

    # chrome
    p = sub.add_parser("chrome", help="Chrome控制")
    p.add_argument("chrome_action", choices=["open", "info", "cookie", "js", "screenshot", "buttons"])
    p.add_argument("--url", help="URL (open用)")
    p.add_argument("--js-code", help="JS代码 (js用)")
    p.add_argument("--output", help="输出路径 (screenshot用)")

    args = parser.parse_args()

    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "explore":
        cmd_explore(args)
    elif args.cmd == "cache":
        cmd_cache(args)
    elif args.cmd == "history":
        cmd_history(args)
    elif args.cmd == "chrome":
        cmd_chrome(args)


if __name__ == "__main__":
    main()
