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
