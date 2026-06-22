# Real Amazon Search Adapter And Runtime Autostart Plan

Date: 2026-06-22 CST
Owner: 听云（agentKey: `tingyun`）
Request: `MSG-20260622-061`
Status: `S2_S3_IMPLEMENTED / PENDING_CODE_REVIEW`

## Background

`MSG-20260622-060` used product `92 / W808P389332` to trigger the official endpoint `POST /api/products/92/competitor-search/retry`. The task runtime created task run `746` and step `752`, then failed at the first real Amazon search boundary:

```text
AmazonSearchPageError: adapter_not_configured
Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization
```

The user authorized real external calls and product status reset in `MSG-20260622-057`, but explicitly forbade mocked interface calls, fake results, and fixture results being treated as real QA PASS.

观止 also observed that task run `746` did not execute during the first polling window until `POST /api/task-runs/746/wake` was called. This is not the main blocker, but it affects the goal that products should advance automatically without manual intervention.

## Current Code Facts

- `backend/app/services/amazon_search_page.py` defines `AmazonSearchPageAdapter`, candidate/result dataclasses, a fixture parser, page classification, and `UnconfiguredAmazonSearchPageAdapter`.
- `get_amazon_search_page_adapter()` currently returns `UnconfiguredAmazonSearchPageAdapter`, so real Amazon search intentionally fails closed.
- `backend/app/services/amazon_competitor_query.py` builds deterministic query plans from product facts.
- `ProductCompetitorSearchAction` in `backend/app/product_tasks/actions.py` validates workflow/protection/main-image/query facts, projects `search_competitor/processing`, executes `run_amazon_search_queries()`, upserts `amazon_competitor_search_candidates`, and projects success to `visual_match_competitors/pending`.
- `POST /api/products/{id}/competitor-search/retry` in `backend/app/api/products.py` uses `create_product_competitor_search_runs(..., auto_start=True)`.
- `create_product_action_runs()` sets the first step to `ready`, commits, then calls `kick_task_runtime()`.
- `backend/app/task_runtime/scheduler.py` is a process-local kick/drain model, not a durable always-on worker. `STARTUP_KICK_TASK_RUNTIME` and `STARTUP_RECOVER_TASKS` default to `False`.
- The repo already has `backend/app/pipeline/chrome_ctrl.py`, a macOS Google Chrome AppleScript controller with workflow serialization and a dedicated worker tab.

## Proposed Solution

Implement a real Chrome-backed Amazon search adapter first, reusing the existing local Chrome controller. Keep the adapter disabled by default. When not explicitly configured and authorized, it must fail closed with a readable `AmazonSearchPageError`; it must not fall back to fixture HTML, cached fake candidates, or mocked results.

The adapter only performs read-only Amazon search page access, parsing, and evidence capture. It must not log in automatically, bypass CAPTCHA, click ads/purchase buttons, access Seller Central, upload exports, or trigger A+/TikTok side effects.

If this flow must later run on a headless remote server or CI, that should become a separate design-change task, likely with Playwright, a persistent browser profile, dependency installation, and an operating runbook. That is outside this first local-real-adapter plan.

## Module Boundaries

- `backend/app/services/amazon_search_page.py`
  - Add `ChromeAmazonSearchPageAdapter`.
  - Build Amazon search URLs.
  - Navigate/read DOM through `chrome_ctrl`.
  - Classify authorization/blocker states.
  - Parse candidates and write evidence.
  - Keep fixture adapter limited to explicit tests.
- `backend/app/config.py`
  - Add explicit real adapter settings, all defaulting safe/disabled.
- `backend/app/product_tasks/actions.py`
  - Keep workflow, protection, task lifecycle, candidate write, and failure projection here.
  - Do not embed browser control logic here.
- `backend/app/task_runtime/scheduler.py`
  - Improve auto-start reliability and observability only within the current process-local runner model.
  - Do not redesign the scheduler into a distributed durable worker in this stage.
- `backend/app/api/products.py`
  - Keep the existing retry endpoint contract.

## Configuration And Authorization

Suggested config:

- `AMAZON_SEARCH_PAGE_ADAPTER=unconfigured|chrome`
- `AMAZON_SEARCH_ENABLE_REAL_BROWSER=false`
- `AMAZON_SEARCH_MARKETPLACE=US`
- `AMAZON_SEARCH_BASE_URL=https://www.amazon.com`
- `AMAZON_SEARCH_PER_QUERY_LIMIT=12`
- `AMAZON_SEARCH_MAX_CANDIDATES=20`
- `AMAZON_SEARCH_NAV_TIMEOUT_SECONDS=45`
- `AMAZON_SEARCH_AFTER_LOAD_WAIT_SECONDS=4`
- `AMAZON_SEARCH_BETWEEN_QUERY_DELAY_SECONDS=10`
- `AMAZON_SEARCH_EVIDENCE_DIR=<DATA_DIR>/task_evidence/amazon_search_page`

Authorization model:

- A human uses the same macOS user session and Google Chrome profile to open Amazon and handle login, location, CAPTCHA, or other gates.
- The task detects page state and returns typed errors such as `login_required`, `captcha`, or `bot_check`; it does not try to bypass them.
- Docker, CI, headless Linux, or remote environments without a GUI Chrome session should fail closed as `browser_unavailable` or `adapter_not_configured`.

## Error Semantics

Use `AmazonSearchPageError(error_type, message)` as the adapter-to-action contract.

Expected error types:

- `adapter_not_configured`
- `browser_unavailable`
- `browser_permission_denied`
- `navigation_timeout`
- `login_required`
- `captcha`
- `bot_check`
- `region_page`
- `unsupported_page_structure`
- `empty_results`
- `parser_error`
- `rate_limited`

`ProductCompetitorSearchAction.on_step_failure()` should continue projecting failures to `search_competitor/failed` with a readable `workflow_error`. CAPTCHA, login, bot-check, region, and permission failures should not auto-retry. The user can fix authorization and retry from the existing product action.

Search success requires at least one parseable ASIN candidate. Empty results are a failure, not a successful empty state.

## Real Adapter Behavior

- Search URL: `https://www.amazon.com/s?k=<query>&language=en_US&ref=nb_sb_noss`
- V1 reads only the first results page.
- Query count remains 1-3 per product through existing query planner.
- Per-query result limit should be 8-12; merged unique candidate cap is 20.
- Use the existing Chrome workflow lock to serialize Amazon page access.
- Add delay/jitter between queries; wait for body/search results; allow one mild scroll if needed.
- Extract `asin`, `url`, `title`, `image_url`, `price`, `rating`, `review_count`, `sponsored`, `search_query`, `search_rank`, and `raw_candidate`.
- Preserve existing downstream candidate flagging/exclusion for sponsored/accessory/replacement/cover-only cases.

Evidence should be written by task run, task step, and query index. It should include URL, page title, classification, candidate JSON, timestamp, adapter/config summary, and either HTML or a DOM summary. Evidence is audit material only; it must not be reused later as a fake live search result.

## Runtime Autostart Analysis

Observed path:

```text
POST /api/products/{id}/competitor-search/retry
-> create_product_competitor_search_runs(auto_start=True)
-> create_product_action_runs()
-> first step set ready
-> db commit
-> kick_task_runtime()
```

Likely causes for the observed need to wake task run `746` manually:

- The scheduler is a process-local kick/drain runner, not a continuously polling worker.
- The `call_later()` callback may not run if the current process/loop reloads or the runner state becomes stale.
- `_runner_task` and `_runner_handle` are process globals; failures are not durably visible.
- Startup settings intentionally do not recover or kick queued work by default.
- There is limited observability when the runner task exits or fails.

Planned repair boundary:

- Add behavior evidence that new `auto_start=True` runs enter `running` or terminal state without manual wake in a normal service process.
- Clean up completed or failed runner state so stale globals do not block later kicks.
- Log runner exceptions and lifecycle events.
- Keep startup recovery/kick controlled by explicit config. Do not silently change safe startup defaults.
- If the project needs cross-process, cross-restart, always-on task consumption, create a separate design-change task.

## Safety

The adapter and task must not modify or override:

- real ASIN
- catalog ASIN
- manual confirmation facts
- export history
- Amazon template outputs
- A+ upload or uploading state
- Seller Central/A+/TikTok state

Allowed writes are task run/step/event records, product workflow/search failure, current search candidates, and task evidence.

## Test Strategy

- Parser and classification tests may use fixture HTML, but only to test parser behavior.
- Default configuration must produce `adapter_not_configured`.
- Real adapter must require explicit config and fail closed when Chrome or authorization is unavailable.
- Project rules should prevent fixture adapter from becoming the default real adapter.
- Runtime behavior tests should prove new `auto_start=True` runs do not require manual wake in the normal service process.
- Validation commands:
  - `python -m compileall backend/app`
  - `make test-project-rules`
  - focused parser/config/runtime behavior scripts
  - frontend build only if user-visible config or UI changes are touched
- Final QA should be run by 观止 on product `92` or another 若命-approved safe sample through the official API.

## Documentation And Index Plan

- Update `docs/domain-index/product-flow.md` with real Amazon search adapter boundary, config, evidence, and failure semantics.
- Update `docs/domain-index/task-runtime.md` with auto-start semantics and wake/troubleshooting.
- Add a runbook or PRD addendum if the final implementation requires manual Chrome authorization steps.
- No Amazon template mapping changelog update is required.

## Stage Plan

### S1: Technical Plan

- Output: this document and inbox `TECHNICAL_PLAN`.
- Code changes: none.
- Gate: 若命 review, then 镜花 design review.

### S2: Adapter And Config

- Files: `backend/app/config.py`, `backend/app/services/amazon_search_page.py`, related tests/rules, relevant domain index.
- Output: real Chrome adapter disabled by default, typed failures, evidence capture, no fake success path.
- Gate: 若命 review and 镜花 code review.

### S3: Runtime Autostart

- Files: `backend/app/task_runtime/scheduler.py`, focused runtime behavior test/script, `docs/domain-index/task-runtime.md`.
- Output: new `auto_start=True` run does not require manual wake in normal service process; runner lifecycle is observable.
- Gate: 若命 review and 镜花 code review.

### S4: Real Small-Sample QA Support

- Files: no core code changes unless S2/S3 review finds gaps.
- Output: product `92` or a 若命-approved safe sample reaches real Amazon candidate landing or a typed real external blocker without manual wake.
- Gate: 观止 QA rerun.

## Open Questions

- Should V1 use existing local Chrome/AppleScript, or does the project require a Playwright persistent-profile adapter now?
- Who completes Amazon browser authorization: user, 观止, or a future diagnostic UI/runbook?
- Should real QA continue with product `92`, or should 若命 select another safe sample?
- Should evidence store full HTML, DOM summaries, or both?

## Risks

- Amazon page structure, location gates, CAPTCHA, and bot checks are unstable and must be treated as real recoverable blockers.
- The local Chrome/AppleScript approach depends on a macOS GUI session and browser permission.
- Slow serial search reduces throughput but fits the current small-sample real QA goal.
- The existing scheduler is not a durable distributed worker; S3 can improve local auto-start reliability but cannot promise cross-restart automation without a separate architecture task.

## Completion Definition

- Unconfigured or unauthorized search fails closed with clear retryable errors and no fake candidates.
- Authorized local Chrome search writes real Amazon candidates to `amazon_competitor_search_candidates`.
- Search evidence is traceable by task run, step, and query.
- Success projects `visual_match_competitors/pending`; failure projects `search_competitor/failed`.
- New `auto_start=True` task runs execute without manual wake in normal service process.
- Documentation and tests clearly distinguish real success, real external blocker, and parser fixture coverage.

## S2/S3 Implementation Notes

Date: 2026-06-22 CST

Implemented scope:

- S2 real adapter/config:
  - `backend/app/config.py` adds fail-closed Amazon search settings. Defaults remain `AMAZON_SEARCH_PAGE_ADAPTER=unconfigured` and `AMAZON_SEARCH_ENABLE_REAL_BROWSER=false`.
  - `AMAZON_SEARCH_MAX_CANDIDATES` is the search-candidate persistence cap fact source. The default remains 20, but `_upsert_competitor_search_candidates()` reads the setting instead of hard-coding the flatten limit.
  - `backend/app/services/amazon_search_page.py` adds `ChromeAmazonSearchPageAdapter`, explicit config gating, typed failures, Chrome/AppleScript read-only search, and evidence files under `AMAZON_SEARCH_EVIDENCE_DIR` grouped by `run-<task_run_id>/step-<task_step_id>/query-<query_index>.json`.
  - `backend/app/product_tasks/actions.py` only passes `product_id/item_code/task_run_id/task_step_id` evidence context into `run_amazon_search_queries()`; browser logic stays inside the adapter.
  - Fixture parser behavior remains available for parser tests only; default and disabled real-browser config paths still raise `adapter_not_configured`.
- S3 runtime auto-start:
  - `backend/app/task_runtime/scheduler.py` adds runner schedule/start/claim/finish logging, runner exception logging, and cleanup of completed/cancelled runner state.
  - The fix does not auto-call wake and does not change startup safety defaults.
  - `scripts/test_task_runtime_autostart.py` now creates a real probe `task_runs/task_groups/task_steps` ready step, registers a probe worker, calls `kick_task_runtime()`, and verifies the step reaches `succeeded` through the normal claim/execute path without manual wake before cleaning up probe rows.

Verification hooks:

- `scripts/test_amazon_search_page_real_adapter_boundaries.py` checks default fail-closed behavior and a typed Chrome permission failure with evidence attribution.
- `scripts/test_task_runtime_autostart.py` checks `kick_task_runtime()` schedules and runs the current-process runner without manual wake and clears stale runner/handle state.
- `scripts/test_project_rules.py` runs both scripts and adds static boundaries for config gating, evidence attribution, ProductTaskAction/browser separation, and runner lifecycle observability.

Still not covered by S2/S3:

- Real human-authorized Amazon page success on product `92` or another safe sample. That is S4/观止 QA scope.
- Remote headless browser, Playwright persistent profile, cross-restart durable worker, or multi-process leader election.
