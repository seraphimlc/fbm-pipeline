import shutil
from pathlib import Path


VIDEO_DIR_NAME = "video"
APLUS_IMAGE_DIR_NAME = "new aplus image"
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
    ".3gp",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}


def _is_in_dir(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _unique_target(directory: Path, filename: str) -> Path:
    target = directory / filename
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    index = 1
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def organize_video_files(material_dir: Path) -> Path | None:
    """Move collected video files into material_dir/video and return the folder when videos exist."""
    if not material_dir.is_dir():
        return None

    video_dir = material_dir / VIDEO_DIR_NAME
    videos: list[Path] = []
    for path in material_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if _is_in_dir(path, video_dir):
            videos.append(path)
            continue
        videos.append(path)

    if not videos:
        return video_dir if video_dir.is_dir() else None

    video_dir.mkdir(parents=True, exist_ok=True)
    for path in videos:
        if _is_in_dir(path, video_dir):
            continue
        target = _unique_target(video_dir, path.name)
        shutil.move(str(path), str(target))

    return video_dir


def folder_summary(folder: Path, extensions: set[str] | None = None, limit: int = 20) -> dict:
    if not folder.is_dir():
        return {
            "path": str(folder),
            "exists": False,
            "file_count": 0,
            "files": [],
        }

    files = [
        path
        for path in folder.rglob("*")
        if path.is_file() and (extensions is None or path.suffix.lower() in extensions)
    ]
    files.sort(key=lambda item: str(item).lower())
    return {
        "path": str(folder),
        "exists": True,
        "file_count": len(files),
        "files": [str(path.relative_to(folder)) for path in files[:limit]],
    }


def video_folder_summary(material_dir: Path, limit: int = 20) -> dict | None:
    """Read-only summary of video files under material_dir."""
    if not material_dir.is_dir():
        return None

    files = [
        path
        for path in material_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    files.sort(key=lambda item: str(item).lower())
    if not files:
        return None
    return {
        "path": str(material_dir),
        "exists": True,
        "file_count": len(files),
        "files": [str(path.relative_to(material_dir)) for path in files[:limit]],
    }


def aplus_folder_summary(folder: Path, limit: int = 20) -> dict:
    if not folder.is_dir():
        return {
            "path": str(folder),
            "exists": False,
            "file_count": 0,
            "files": [],
        }

    files = []
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stem = path.stem.lower()
        if stem.endswith("_raw") or "_backup_" in stem:
            continue
        files.append(path)

    files.sort(key=lambda item: str(item).lower())
    return {
        "path": str(folder),
        "exists": True,
        "file_count": len(files),
        "files": [str(path.relative_to(folder)) for path in files[:limit]],
    }


def aplus_image_folder(material_dir: Path) -> Path:
    return material_dir / APLUS_IMAGE_DIR_NAME
