"""Local recording/tool configuration. Do not put credentials or paths in source."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("VIDEO_EDITOR_SOURCE", str(ROOT/"unconfigured-source.mp4")))
FFMPEG = os.environ.get("VIDEO_EDITOR_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("VIDEO_EDITOR_FFPROBE", "ffprobe")


def source_duration():
    manifest = ROOT/"manifest.json"
    if not manifest.exists():
        return 0
    return float(json.loads(manifest.read_text(encoding="utf-8")).get("source_duration_seconds", 0))
