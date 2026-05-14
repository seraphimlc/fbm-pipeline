---
name: fix-permissionerror
description: 错误恢复方案
version: 1.0
auto_generated: true
pattern_type: error_recovery
---

# fix-permissionerror

错误恢复方案

## 触发条件

- 遇到 `PermissionError` 类型错误时触发

## 执行步骤

1. 使用 `exec` 执行: sudo chmod 755

## 验证方法

- 错误不再出现
- 操作成功完成

## 元数据

- 模式ID: 520e952f-42f1-4fd1-b95b-1c6b1d0c16b2
- 出现次数: 1
- 首次出现: 2026-04-15 17:52:48.390801
- 最后出现: 2026-04-15 17:52:48.390801
- 自动生成时间: 2026-04-15T17:52:48.393245
