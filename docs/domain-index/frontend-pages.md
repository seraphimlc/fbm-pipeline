# Domain Index: Frontend Pages

## 范围

- 前端路由、页面入口、API client、导航和页面冒烟路径。
- 页面交互问题的定位顺序。
- 不记录具体 UI bug 修复过程。

## 当前口径

- 路由定义在 `frontend/src/App.tsx`。
- 页面 API 调用集中从 `frontend/src/api/index.ts` 定位。
- 状态/按钮/统计问题优先确认后端稳定字段，不让前端自行推导。
- 不通过隐藏按钮、堆 badge、堆说明文案掩盖后端语义不清。

## 关键入口

- 路由：`frontend/src/App.tsx`
- Layout/导航：`frontend/src/components/MainLayout.tsx`
- API client：`frontend/src/api/index.ts`
- 全局样式：`frontend/src/index.css`
- 商品列表：`frontend/src/pages/ProductList.tsx`
- Amazon 详情：`frontend/src/pages/ProductDetail.tsx`
- TikTok 详情：`frontend/src/pages/TikTokProductDetail.tsx`
- 图片确认：`frontend/src/pages/ProductImageReview.tsx`
- 竞品确认：`frontend/src/pages/ProductCompetitorReview.tsx`
- 新任务中心：`frontend/src/pages/TaskRunCenter.tsx`
- 旧离线任务中心：`frontend/src/pages/OfflineTaskCenter.tsx`
- 导出中心：`frontend/src/pages/CatalogList.tsx`
- 数据源：`frontend/src/pages/ProductDataSourceList.tsx`

## 关键流程

- 页面定位：路由 -> page component -> API client -> backend API。
- 状态/按钮问题：page component -> API response fields -> backend display/projection。
- 页面冒烟：打开页面 -> 检查 loading/error/empty/data 状态 -> 对应 API 样本。

## 相关文档

- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/domain-index/export-flow.md`
- `docs/domain-index/data-sources.md`
- `docs/collaboration/playbooks/qa.md`
- `docs/collaboration/playbooks/code-review.md`

## 验证入口

- 构建：`cd frontend && npm run build`
- 商品列表：`http://localhost:3190/products`
- 任务中心：`http://localhost:3190/task-runs`
- 导出中心：`http://localhost:3190/export-center`
- 数据源：`http://localhost:3190/data-sources`

## 常见定位

- 路由问题：先看 `frontend/src/App.tsx`。
- 导航问题：先看 `frontend/src/components/MainLayout.tsx`。
- API 字段问题：先看 `frontend/src/api/index.ts`，再到对应后端 API。
- 页面慢/阻塞：先看页面首屏请求和非首屏请求是否拆开。
- 状态/按钮/统计问题：先看后端是否提供明确字段。

## 维护规则

只有路由、页面入口、API client 主要方法、导航入口或主要验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
