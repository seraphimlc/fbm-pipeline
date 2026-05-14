---
name: browser-pilot
description: "万能浏览器操作框架：渐进式自动化，API直连 > DOM操作 > 多模态点击。自动学习并缓存成功路径，越用越快。"
compatibility: darwin
metadata:
  version: 1.0.0
  requires:
    bins:
      - python3
      - osascript
      - cliclick
    python_packages:
      - openpyxl
---

# Browser Pilot — 万能浏览器操作框架

**渐进式自动化**：从最轻量到最重量级逐步升级，成功操作自动固化，越用越快。

## 何时使用

- 需要操作本地Chrome浏览器（有登录态的网站）
- 需要自动化网页操作（点击、填写、下载等）
- 用户说"帮我打开XX网站做XX"、"自动操作XX"
- 其他Skill需要浏览器操作能力时，引用本框架

## 核心策略：3层渐进 + 自动学习

```
第1层（最快）：API/URL直连 → 0交互，直接请求
第2层（中等）：DOM操作 → AppleScript+JS查找元素点击
第3层（最重）：多模态 → 截屏+VLM识别+模拟鼠标
```

**关键**：每层成功后，将成功的路径记录到缓存。下次优先走最快路径，失败再逐层降级。

## 工作流程

### 首次操作（无缓存）

```
1. 打开目标页面（AppleScript控制Chrome）
2. 尝试DOM操作（JS查找元素+点击）
   ├─ 成功 → 记录URL+选择器到缓存 → 完成 ✅
   └─ 失败 → 进入第3层
3. 多模态操作（截屏→VLM识别→模拟点击→验证）
   ├─ 成功 → 记录URL+位置描述到缓存 → 完成 ✅
   └─ 失败 → 报错
4. 探索阶段：尝试拦截网络请求，发现API地址
   └─ 发现API → 记录到缓存（最高优先级）
```

### 后续操作（有缓存）

```
1. 优先走缓存的最快路径
   ├─ 有API URL → 直接请求 → 校验结果
   │   ├─ 成功 → 完成 ✅
   │   └─ 失败 → 降级到第2层
   ├─ 有Page URL → 直接跳转 → DOM操作
   │   ├─ 成功 → 完成 ✅
   │   └─ 失败 → 降级到第3层
   └─ 无缓存 → 按首次操作流程
2. 第2层：DOM操作（选择器多层降级）
   ├─ CSS选择器 → 文字匹配 → ARIA标签
   ├─ 成功 → 更新缓存 → 完成 ✅
   └─ 全部失败 → 降级到第3层
3. 第3层：多模态操作
   ├─ 截屏 → VLM识别 → 模拟点击 → 验证
   ├─ 成功 → 更新缓存 → 完成 ✅
   └─ 失败 → 报错
```

## 操作配置文件

每个网站/功能的操作配置存放在 `references/actions/` 目录下，JSON格式：

```json
{
  "id": "sellersprite_keyword_export",
  "name": "卖家精灵关键词反查导出",
  "site": "sellersprite.com",
  "description": "输入ASIN，导出关键词反查Excel",

  "auth": {
    "type": "cookie",
    "required_cookies": ["Sprite-X-Token"],
    "token_lifetime_hours": 24,
    "refresh_method": "chrome_cookie"
  },

  "layers": {
    "api": {
      "method": "POST",
      "url": "https://www.sellersprite.com/v3/api/relation/ta/export-keyword-new",
      "params": {"market": "1", "exportVariations": "false", "exportGkImages": "false"},
      "body_template": {"asin": "{ASIN}"},
      "headers": {
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": "https://www.sellersprite.com/v3/keyword-reverse"
      },
      "response_type": "blob",
      "verify": {"http_status": 200, "content_type": "application/octet-stream"},
      "verified_date": "2026-05-01"
    },

    "page": {
      "url_template": "https://www.sellersprite.com/v3/keyword-reverse?q={ASIN}&marketId=1",
      "steps": [
        {
          "action": "navigate",
          "url_template": "https://www.sellersprite.com/v3/keyword-reverse?q={ASIN}&marketId=1",
          "verify": {"title_contains": "关键词反查"}
        },
        {
          "action": "click",
          "selectors": [
            {"type": "css", "value": "button.el-button.my-btn.success-border"},
            {"type": "text", "value": "导出", "exclude": "导出明细"},
            {"type": "aria", "value": "导出"}
          ],
          "verify": {"download_started": "ReverseASIN-US-{ASIN}"}
        },
        {
          "action": "wait",
          "seconds": 3
        }
      ]
    },

    "multimodal": {
      "steps": [
        {"action": "screenshot"},
        {"action": "vlm_identify", "prompt": "找到'导出'按钮的位置"},
        {"action": "mouse_click", "position": "vlm_result"},
        {"action": "wait", "seconds": 2},
        {"action": "screenshot"},
        {"action": "vlm_verify", "prompt": "是否出现了下载或导出成功的提示？"}
      ]
    }
  },

  "fallback_order": ["api", "page", "multimodal"],
  "last_used_layer": "api",
  "last_success_date": "2026-05-01"
}
```

## Agent操作指南

### 执行一个已配置的操作

```bash
# 查看所有已配置的操作
python3 scripts/pilot.py list

# 执行操作（自动选择最快路径）
python3 scripts/pilot.py run sellersprite_keyword_export --params '{"ASIN": "B0GMWKDNBC"}'

# 强制使用指定层
python3 scripts/pilot.py run sellersprite_keyword_export --layer page --params '{"ASIN": "B0GMWKDNBC"}'

# 查看操作历史
python3 scripts/pilot.py history sellersprite_keyword_export
```

### 探索新操作（无配置时）

```bash
# 交互式探索：打开页面 → 尝试DOM → 记录结果
python3 scripts/pilot.py explore --url "https://example.com" --action "点击下载按钮"
```

### 管理缓存

```bash
# 查看缓存状态
python3 scripts/pilot.py cache status

# 更新某个操作的最快路径
python3 scripts/pilot.py cache update sellersprite_keyword_export --layer api

# 清除某个操作的缓存（下次重新探索）
python3 scripts/pilot.py cache clear sellersprite_keyword_export
```

## AppleScript + JS 命令参考

### 打开URL
```applescript
tell application "Google Chrome"
    tell active tab of front window
        set URL to "<URL>"
    end tell
end tell
```

### JS查找元素（多层降级）
```javascript
(function() {
    var target = "<TARGET_TEXT>";
    var exclude = "<EXCLUDE_TEXT>";
    
    // 第1层：CSS选择器
    var el = document.querySelector("<CSS_SELECTOR>");
    if (el) return JSON.stringify({found: true, method: "css", tag: el.tagName});
    
    // 第2层：文字匹配
    var btns = document.querySelectorAll("button, a, [role='button'], [onclick]");
    for (var i = 0; i < btns.length; i++) {
        var text = btns[i].innerText.trim();
        if (text === target || text.includes(target)) {
            if (exclude && text.includes(exclude)) continue;
            btns[i].click();
            return JSON.stringify({found: true, method: "text", tag: btns[i].tagName, text: text});
        }
    }
    
    // 第3层：ARIA标签
    var aria = document.querySelector("[aria-label*='" + target + "']");
    if (aria) { aria.click(); return JSON.stringify({found: true, method: "aria"}); }
    
    return JSON.stringify({found: false, error: "element not found"});
})()
```

### JS获取页面信息
```javascript
(function() {
    return JSON.stringify({
        title: document.title,
        url: location.href,
        buttons: Array.from(document.querySelectorAll("button")).slice(0, 20).map(b => ({
            text: b.innerText.trim().substring(0, 50),
            className: b.className.substring(0, 80),
            disabled: b.disabled,
            visible: b.offsetParent !== null
        }))
    });
})()
```

### 截屏
```bash
screencapture -x /tmp/browser_pilot_screenshot.png
```

### 模拟鼠标点击
```bash
# cliclick方式（精确坐标）
cliclick c:500,300

# AppleScript方式（相对当前窗口）
osascript -e 'tell application "System Events" to click at {500, 300}'
```

## 结果校验

每层操作后必须校验结果，不能只看HTTP状态码：

| 校验类型 | 说明 | 示例 |
|---------|------|------|
| http_status | HTTP状态码 | 200 |
| content_type | 响应内容类型 | application/octet-stream |
| title_contains | 页面标题包含 | "关键词反查" |
| download_started | 下载文件出现 | ReverseASIN-US-{ASIN} |
| element_visible | 元素可见 | 成功提示框出现 |
| element_gone | 元素消失 | loading图标消失 |
| custom_js | 自定义JS校验 | `document.querySelector('.success-msg') !== null` |

## 认证管理

| 方式 | 说明 | 自动刷新 |
|------|------|---------|
| chrome_cookie | 从Chrome读取Cookie | ✅ 自动 |
| bearer_token | HTTP Bearer Token | ⚠️ 需配置刷新接口 |
| basic_auth | 用户名密码 | ❌ 手动 |
| session_cookie | 会话Cookie | ✅ 从Chrome刷新 |

## 多步骤操作链

复杂操作可能需要多步，每步独立校验：

```json
{
  "steps": [
    {"action": "navigate", "url": "...", "verify": {"title_contains": "登录"}},
    {"action": "fill", "selectors": [...], "value": "{username}", "verify": {"element_visible": "密码框"}},
    {"action": "click", "selectors": [...], "verify": {"title_contains": "首页"}},
    {"action": "click", "selectors": [...], "verify": {"download_started": "report.xlsx"}}
  ]
}
```

如果某步失败，只从该步开始降级，不需要从头来。

## 异常处理

| 情况 | 处理 |
|------|------|
| Chrome未运行 | 启动Chrome，等待5秒 |
| 页面加载超时 | 等待10秒，刷新重试1次 |
| 选择器失效 | 降级到文字匹配→ARIA→多模态 |
| Token过期 | 从Chrome重新读取Cookie |
| 多模态点击无响应 | 等待2秒再截屏验证，失败则重试1次 |
| 所有层都失败 | 报错，建议用户手动操作 |

## 与其他Skill的关系

- **sellersprite-data-collector**: 使用本框架的配置驱动模式，已配置 `sellersprite_keyword_export`
- **gigab2b-download**: 可使用本框架探索大健云仓的操作路径
- 其他需要浏览器操作的Skill: 创建对应的action配置文件即可

## 版本历史

- **v1.0.0** (2026-05-01): 初始版本，3层渐进+自动学习框架
