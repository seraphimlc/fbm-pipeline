"""Fast no-network contract checks for Amazon image XMP compliance helpers."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import amazon_image_compliance as compliance


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="xmp-contract-") as temp:
        image = Path(temp) / "fixture.jpg"
        image.write_bytes(b"image-fixture")
        subjects = ["supplier-keyword"]

        def fake_run(*args: str):
            nonlocal subjects
            if args[0] == "-j":
                return subprocess.CompletedProcess([], 0, json.dumps([{"Subject": subjects}]), "")
            if any("XMP-dc:Subject+=" in item for item in args):
                subjects.append(compliance.SYNTHETIC_PERFORMER_SUBJECT)
            return subprocess.CompletedProcess([], 0, "", "")

        original_run = compliance._run
        original_download = compliance.download_private_file
        try:
            compliance._run = fake_run
            first = compliance.ensure_synthetic_performer_subject(image)
            second = compliance.ensure_synthetic_performer_subject(image)
            assert subjects == ["supplier-keyword", compliance.SYNTHETIC_PERFORMER_SUBJECT], subjects
            assert first["sha256"] == second["sha256"]

            downloaded = Path(temp) / "downloaded.jpg"
            compliance.download_private_file = lambda _key, target: target.write_bytes(image.read_bytes())
            evidence = compliance.verify_oss_round_trip("qa/fixture.jpg", image, downloaded)
            assert evidence["oss_round_trip_verified"] is True
            assert compliance.SYNTHETIC_PERFORMER_SUBJECT in evidence["subject"]
        finally:
            compliance._run = original_run
            compliance.download_private_file = original_download
    print("Amazon image compliance helper contracts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
