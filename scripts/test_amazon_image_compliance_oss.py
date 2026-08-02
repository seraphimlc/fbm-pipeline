"""Explicit real-OSS round-trip gate for Amazon synthetic-performer XMP metadata.

This test never runs implicitly. It reports SKIPPED when OSS/ExifTool are not
configured, and uses a UUID-only object which is deleted in finally.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image
from app.services.amazon_image_compliance import ensure_synthetic_performer_subject, verify_oss_round_trip
from app.services.oss_uploader import delete_private_file, oss_configured, upload_private_file


def main() -> int:
    if not oss_configured() or not shutil.which("exiftool"):
        print("SKIPPED: real OSS or ExifTool is not configured; no claim of OSS verification.")
        return 0
    with tempfile.TemporaryDirectory(prefix="amazon-image-compliance-") as temp:
        work = Path(temp)
        image = work / "fixture.jpg"
        downloaded = work / "downloaded.jpg"
        Image.new("RGB", (32, 32), "white").save(image, "JPEG")
        ensure_synthetic_performer_subject(image)
        object_key = f"compliance-qa/{uuid4().hex}.jpg"
        try:
            upload_private_file(image, object_key)
            evidence = verify_oss_round_trip(object_key, image, downloaded)
            assert evidence["oss_round_trip_verified"], evidence
            print("PASS: OSS round-trip preserved contains-synthetic-performer and SHA-256")
        finally:
            delete_private_file(object_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
