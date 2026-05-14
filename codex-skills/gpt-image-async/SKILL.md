---
name: "gpt-image-async"
description: "异步生图API（GPT-Image-2）。当需要生成新图片、制作产品主图、创建白底图、生成营销素材时使用。支持提交异步任务+查询结果+一键等待下载。"
---

# GPT Image Async

异步生图API，基于 GPT-Image-2 模型。

## 配置

API配置在 `scripts/config.json`：
- `api_key`: API密钥
- `base_url`: API地址（https://ai.t8star.cn）
- `model`: gpt-image-2
- `default_size`: 2048x1152

## 使用方式

### 一键生图（推荐）

提交+等待+下载，一步到位：

```bash
uv run python scripts/generate_and_wait.py --prompt "描述" --size 2048x1152 --output /tmp/image.png
```

### 分步操作

1. 提交任务：
```bash
uv run python scripts/generate.py --prompt "描述" --size 2048x1152
```

2. 查询结果：
```bash
uv run python scripts/query.py --task_id TASK_ID
```

## 参数说明

- `--prompt`：生图描述（必填）
- `--size`：尺寸，默认2048x1152。两边必须是16的倍数，最大3840px，长宽比≤3:1（会自动向上取整）
- `--n`：数量，默认1
- `--output`：输出路径（generate_and_wait专用）
- `--timeout`：等待超时秒数，默认300（generate_and_wait专用）

## 典型场景

### 生成亚马逊白底主图
```bash
uv run python scripts/generate_and_wait.py \
  --prompt "Product photo of a grey modular sectional sofa on pure white background, studio lighting, no shadows, no text, no watermark, Amazon main image style" \
  --size 2048x2048 \
  --output /tmp/main_image.png
```

### 参考图生图（需先描述参考图内容）
先分析参考图内容，再将描述融入prompt。

## 注意事项

- 异步模式：提交后返回task_id，需轮询查询
- 尺寸自动调整：1940×1200 → 1952×1200（向上取整到16的倍数）
- 生成时间通常30-120秒
- 不支持透明背景（gpt-image-2限制）
