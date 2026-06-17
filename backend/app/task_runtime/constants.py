RUN_STATUS_PENDING = "pending"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_PARTIAL_FAILED = "partial_failed"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_STATUS_PAUSED = "paused"
RUN_STATUS_CANCELED = "canceled"

STEP_STATUS_PENDING = "pending"
STEP_STATUS_READY = "ready"
STEP_STATUS_RUNNING = "running"
STEP_STATUS_SUCCEEDED = "succeeded"
STEP_STATUS_FAILED = "failed"
STEP_STATUS_INTERRUPTED = "interrupted"
STEP_STATUS_SKIPPED = "skipped"
STEP_STATUS_CANCELED = "canceled"

TERMINAL_STEP_STATUSES = {
    STEP_STATUS_SUCCEEDED,
    STEP_STATUS_FAILED,
    STEP_STATUS_INTERRUPTED,
    STEP_STATUS_SKIPPED,
    STEP_STATUS_CANCELED,
}

RETRYABLE_STEP_STATUSES = {
    STEP_STATUS_FAILED,
    STEP_STATUS_INTERRUPTED,
}

GIGA_PULL_GROUPS = (
    ("plan", "规划 SKU 列表"),
    ("details", "拉取 SKU 详情"),
    ("inventory", "拉取 SKU 库存"),
    ("prices", "拉取 SKU 价格"),
    ("finalize", "校验 SKU 快照"),
    ("aggregate", "聚合 Item/Group"),
    ("materialize", "生成商品草稿"),
)
