"""Amazon synthetic-performer XMP compliance helpers.

Only delivery copies are modified.  Supplier originals and user-selected source
files must never be rewritten by this module.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.services.oss_uploader import download_private_file

SYNTHETIC_PERFORMER_SUBJECT = "contains-synthetic-performer"


class ImageComplianceError(RuntimeError):
    pass


def _exiftool() -> str:
    return str(settings.IMAGE_COMPLIANCE_EXIFTOOL_PATH or "exiftool")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run([_exiftool(), *args], check=True, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        raise ImageComplianceError(f"未找到 ExifTool ({_exiftool()})，无法写入 Amazon 图片合规元数据") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ImageComplianceError(f"ExifTool 元数据操作失败: {detail}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_subjects(path: Path) -> list[str]:
    if not path.is_file():
        raise ImageComplianceError(f"图片不存在: {path}")
    payload = json.loads(_run("-j", "-XMP-dc:Subject", str(path)).stdout or "[]")
    if not payload:
        return []
    value = payload[0].get("Subject")
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if value else []


def ensure_synthetic_performer_subject(path: Path) -> dict[str, Any]:
    subjects_before = read_subjects(path)
    if SYNTHETIC_PERFORMER_SUBJECT not in subjects_before:
        _run("-overwrite_original", f"-XMP-dc:Subject+={SYNTHETIC_PERFORMER_SUBJECT}", str(path))
    subjects_after = read_subjects(path)
    if subjects_after.count(SYNTHETIC_PERFORMER_SUBJECT) != 1:
        raise ImageComplianceError("XMP-dc:Subject 未能写入唯一的 contains-synthetic-performer 标记")
    return {"subject": subjects_after, "tagged": True, "sha256": sha256_file(path)}


def prepare_delivery_copy(source: str, destination: Path) -> Path:
    """Copy/download an image into a managed delivery asset without touching source."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.lower().startswith(("http://", "https://")):
        try:
            response = httpx.get(source, timeout=30, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ImageComplianceError(f"下载远程图片失败: {type(exc).__name__}: {exc}") from exc
        destination.write_bytes(response.content)
    else:
        source_path = Path(source).expanduser()
        if not source_path.is_file():
            raise ImageComplianceError(f"本地图片不存在: {source_path}")
        shutil.copy2(source_path, destination)
    return destination


def verify_oss_round_trip(object_key: str, local_path: Path, download_path: Path) -> dict[str, Any]:
    """Download the exact uploaded object and prove both XMP and bytes survived."""
    download_private_file(object_key, download_path)
    subjects = read_subjects(download_path)
    if subjects.count(SYNTHETIC_PERFORMER_SUBJECT) != 1:
        raise ImageComplianceError("OSS 回读文件缺少 contains-synthetic-performer 标记")
    if sha256_file(local_path) != sha256_file(download_path):
        raise ImageComplianceError("OSS 回读文件哈希不一致，拒绝使用可能被重编码的图片")
    return {"oss_round_trip_verified": True, "oss_download_sha256": sha256_file(download_path), "subject": subjects}
