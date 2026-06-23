"""Status registry for Lingxing A+ publish state.

The registry is the domain source of truth for Product/Catalog
``aplus_upload_status`` values. Task runs own execution lifecycle; these values
describe the external publish/business state only.
"""

from __future__ import annotations

from dataclasses import dataclass


STATUS_NOT_UPLOADED = "not_uploaded"
STATUS_CHECKING = "checking"
STATUS_WAITING_LISTING = "waiting_listing"
STATUS_SYNCING_LISTING = "syncing_listing"
STATUS_READY_TO_UPLOAD = "ready_to_upload"
STATUS_UPLOADING = "uploading"
STATUS_DRAFT_SAVED = "draft_saved"
STATUS_DRAFT_CONFIRMING = "draft_confirming"
STATUS_DRAFT_VISIBLE = "draft_visible"
STATUS_SUBMITTED = "submitted"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_AUTH_REQUIRED = "auth_required"


@dataclass(frozen=True)
class AplusPublishStatus:
    key: str
    label: str
    terminal: bool
    retryable: bool
    protected: bool
    visibility_endpoint: bool = False


STATUS_REGISTRY: dict[str, AplusPublishStatus] = {
    STATUS_NOT_UPLOADED: AplusPublishStatus(STATUS_NOT_UPLOADED, "未进入领星发布", False, False, False),
    STATUS_CHECKING: AplusPublishStatus(STATUS_CHECKING, "正在检查前置条件", False, False, False),
    STATUS_WAITING_LISTING: AplusPublishStatus(STATUS_WAITING_LISTING, "等待 Listing / ASIN 对齐", False, True, False),
    STATUS_SYNCING_LISTING: AplusPublishStatus(STATUS_SYNCING_LISTING, "正在同步 Listing / ASIN", False, False, False),
    STATUS_READY_TO_UPLOAD: AplusPublishStatus(STATUS_READY_TO_UPLOAD, "前置满足，等待上传", False, True, False),
    STATUS_UPLOADING: AplusPublishStatus(STATUS_UPLOADING, "正在上传/保存 A+", False, False, True),
    STATUS_DRAFT_SAVED: AplusPublishStatus(STATUS_DRAFT_SAVED, "已保存领星草稿", True, True, True),
    STATUS_DRAFT_CONFIRMING: AplusPublishStatus(STATUS_DRAFT_CONFIRMING, "正在确认 Amazon 草稿可见性", False, False, True),
    STATUS_DRAFT_VISIBLE: AplusPublishStatus(STATUS_DRAFT_VISIBLE, "Amazon 草稿已可见/已同步", True, False, True, True),
    STATUS_SUBMITTED: AplusPublishStatus(STATUS_SUBMITTED, "已提交审批", True, False, True, True),
    STATUS_FAILED: AplusPublishStatus(STATUS_FAILED, "执行失败，可重试", True, True, False),
    STATUS_SKIPPED: AplusPublishStatus(STATUS_SKIPPED, "已跳过", True, False, False),
    STATUS_AUTH_REQUIRED: AplusPublishStatus(STATUS_AUTH_REQUIRED, "需要重新登录领星", True, True, False),
}

ALL_APLUS_PUBLISH_STATUSES: tuple[str, ...] = tuple(STATUS_REGISTRY)
TERMINAL_APLUS_PUBLISH_STATUSES = frozenset(key for key, value in STATUS_REGISTRY.items() if value.terminal)
RETRYABLE_APLUS_PUBLISH_STATUSES = frozenset(key for key, value in STATUS_REGISTRY.items() if value.retryable)
PROTECTED_APLUS_PUBLISH_STATUSES = frozenset(key for key, value in STATUS_REGISTRY.items() if value.protected)
VISIBILITY_ENDPOINT_STATUSES = frozenset(key for key, value in STATUS_REGISTRY.items() if value.visibility_endpoint)

# Legacy Product/Catalog values may be read from existing rows. New writers must
# not produce these keys.
LEGACY_APLUS_PUBLISH_STATUS_MAP: dict[str, str] = {
    "pending": STATUS_CHECKING,
    "running": STATUS_UPLOADING,
}
ITEM_ONLY_LEGACY_STATUSES = frozenset({"success"})


class UnknownAplusPublishStatus(ValueError):
    """Raised when a Product/Catalog publish status is not registered."""


def normalize_aplus_publish_status(value: str | None, *, allow_legacy: bool = True) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return STATUS_NOT_UPLOADED
    if normalized in STATUS_REGISTRY:
        return normalized
    if allow_legacy and normalized in LEGACY_APLUS_PUBLISH_STATUS_MAP:
        return LEGACY_APLUS_PUBLISH_STATUS_MAP[normalized]
    if normalized in ITEM_ONLY_LEGACY_STATUSES:
        raise UnknownAplusPublishStatus(
            f"{normalized!r} is an item/batch execution status, not a Product/Catalog A+ publish status"
        )
    raise UnknownAplusPublishStatus(f"Unknown A+ publish status: {normalized}")


def is_terminal_status(value: str | None) -> bool:
    return normalize_aplus_publish_status(value) in TERMINAL_APLUS_PUBLISH_STATUSES


def is_retryable_status(value: str | None) -> bool:
    return normalize_aplus_publish_status(value) in RETRYABLE_APLUS_PUBLISH_STATUSES


def is_protected_status(value: str | None) -> bool:
    return normalize_aplus_publish_status(value) in PROTECTED_APLUS_PUBLISH_STATUSES


def is_visibility_endpoint_status(value: str | None) -> bool:
    return normalize_aplus_publish_status(value) in VISIBILITY_ENDPOINT_STATUSES
