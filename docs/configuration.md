# Configuration Policy

This project follows a simple rule: committed files contain safe defaults and examples only; real environment values live outside Git.

## Sources Of Truth

### Backend Runtime

Backend runtime configuration is defined by `backend/app/config.py` and loaded from:

1. Process environment variables
2. `backend/.env`
3. Safe defaults in `backend/app/config.py`

`backend/.env.example` is the committed template. `backend/.env` is local-only and ignored by Git.

Relative paths in `backend/.env` are resolved relative to the `backend/` directory. For example:

```env
DATA_DIR=../data
PRODUCT_BASE_DIR=../data/products
```

These resolve to repository-local directories in a fresh clone.

### Frontend Development

Frontend development configuration is loaded by Vite from:

1. Process environment variables
2. `frontend/.env`
3. `frontend/.env.example`

Only `VITE_*` variables should be used for browser-visible values. The frontend should call the backend through relative `/api` URLs; the Vite dev proxy controls where `/api` is forwarded.

Committed frontend defaults:

```env
VITE_BACKEND_URL=http://localhost:8190
VITE_FRONTEND_PORT=3190
```

### Helper Scripts And Skills

Helper scripts must not require committed secret files.

The GPT image helper under `codex-skills/gpt-image-async/scripts/` loads configuration in this order:

1. `scripts/config.json` for committed non-secret defaults
2. `backend/.env` for normal app credentials
3. `scripts/config.local.json` for local script-only overrides
4. Process environment variables as the final override

`scripts/config.local.json` is ignored by Git. Use it only for local development. Prefer `backend/.env` when the script is part of the application workflow.

## What Goes Where

| Value | Location | Committed |
| --- | --- | --- |
| Safe default ports | `backend/app/config.py`, `frontend/.env.example` | Yes |
| Local backend API keys | `backend/.env` or process env | No |
| Local OSS credentials | `backend/.env` or process env | No |
| Local SellerSprite token | `backend/.env` or process env | No |
| Local GIGA Open API credentials | `backend/.env` or process env | No |
| Local product material root | `backend/.env` | No |
| Frontend dev backend URL | `frontend/.env` | No |
| Script-only image API override | `codex-skills/gpt-image-async/scripts/config.local.json` | No |
| Amazon template mapping JSON | `backend/app/pipeline/template_mappings/*.json` | Yes |
| Amazon template XLSM files | `backend/app/pipeline/templates/*.xlsm` | Yes |
| Generated product data, images, DB files, logs | `data/`, `logs/`, `backend/data/` | No |

## Fresh Clone Setup

```bash
git clone git@github.com:seraphimlc/fbm-pipeline.git
cd fbm-pipeline
./scripts/setup_local.sh
./scripts/start.sh
```

`setup_local.sh` creates local `.env` files from templates, prepares `data/products`, creates the backend virtual environment, and installs dependencies.

## Adding New Configuration

When adding a new setting:

1. Add a typed field to `backend/app/config.py` if the backend needs it.
2. Add the same key to `backend/.env.example` if users may need to edit it.
3. Add it to `backend/app/api/config_api.py` only if the UI should edit it.
4. Add a `VITE_*` key to `frontend/.env.example` only if the browser or Vite dev server needs it.
5. Never add real secrets to committed files.

## GIGA Open API Sync

GIGA 拉品使用 Open API，不依赖 Chrome 页面爬取。店铺 API 地址、AK/SK、站点和履约方式只在「数据源维护」里配置，不再写入全局 `backend/.env`：

```env
GIGA_SYNC_PAGE_SIZE=200
```

同步入口：

```bash
cd /path/to/fbm-pipeline
source backend/.venv/bin/activate
python scripts/giga_sync.py --batch-id 20260601-us-b001 --site US --data-source-id 1 --category "furniture"
```

后端也提供 API：

```http
POST /api/giga/sync
GET /api/giga/batches
GET /api/giga/groups?batch_id=20260601-us-b001&site=US
```

GIGA 原始事实落在数据库表 `giga_raw_sku_details`、`giga_items`、`giga_skus`、`giga_prices`、`giga_inventory`、`giga_groups`，全部以 `batch_id + site` 隔离。下游读取 GIGA 商品真相时不要读临时 JSON/XLSX，要按批次和站点从这些表读取。

价格和库存可独立按日同步，不需要每天重拉商品详情。完整设计见 `docs/giga-inventory-sync.md`。

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
cd backend && source .venv/bin/activate && cd ..
python scripts/giga_inventory_sync.py --site US --data-source-id 1 --task-id daily-giga-inventory
python scripts/giga_price_sync.py --site US --data-source-id 1 --task-id daily-giga-price
```

建议在服务器 cron 中每天执行一次，必须显式传 `--site US` 或 `--site JP`，并传 `--data-source-id` 指向对应数据源。不传 `--batch-id` 时脚本会生成 `YYYYMMDD-{site}-inventory` 或 `YYYYMMDD-{site}-price`，同一天重跑会覆盖同一个动态快照批次，不会覆盖其它日期或其它站点。

库存和价格真源为数据库：

- `giga_sync_batches`: 当前复用为动态同步日志表，库存 batch 使用 `current_category=inventory_snapshot` 标识，价格 batch 使用 `current_category=price_snapshot` 标识，记录 `status`、`inventory_count`/`price_count`、`started_at`、`finished_at`、`error_message`。后续如需进一步解耦，可新增专用日志表。
- `giga_prices`: 每次价格快照，复合唯一键 `batch_id + site + sku_code`，包含基础价、专属价、折扣价、有效成交价、运费、预估运费、`task_id`、`pulled_at`。
- `giga_inventory`: 每次库存快照，复合唯一键 `batch_id + site + sku_code`，包含 `stock_qty`、seller/buyer 库存、仓库分布、`task_id`、`pulled_at`。
- `giga_inventory_alerts`: 和上一库存 batch 对比后的有货/无货切换告警，`change_type=out_of_stock/restocked`。
- `giga_price_alerts`: 和上一价格 batch 对比后的有效成交价变化告警，`change_type=price_changed`。

Amazon 库存更新模板导出、以及普通 Amazon 导入表格中的数量覆盖，均读取最新 `giga_inventory.stock_qty`。不要再依赖 `catalog_products.stock` 作为导出库存来源。

前端库存页面 `/inventory-sync` 展示最新 GIGA 库存快照，按 SKU 分页，不再展示旧库存同步批次列表。

API 调用：

- `POST /api/giga/inventory/sync`: 拉取库存快照并生成告警。
- `POST /api/giga/price/sync`: 拉取价格快照。
- `GET /api/giga/inventory?site=US&page=1&page_size=50`: 分页查看最新库存 SKU。
- `GET /api/giga/inventory/alerts?site=US&batch_id=...`: 查看库存切换告警。
- `GET /api/giga/price/alerts?site=US&batch_id=...`: 查看价格变化告警。

## Validation

Before committing configuration changes, run:

```bash
bash -n scripts/setup_local.sh scripts/start.sh
cd backend && source .venv/bin/activate && python -m compileall -q app
cd frontend && npm run build
python3 -m py_compile codex-skills/gpt-image-async/scripts/*.py
```

Before pushing public/shared branches, scan for secrets:

```bash
rg -n -i --hidden --glob '!.git/**' --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!data/**' --glob '!logs/**' --glob '!**/config.local.json' 'sk-[A-Za-z0-9_-]{20,}|api_key"\s*:\s*"sk-|secret_key"\s*:\s*"[^Y]' .
```
