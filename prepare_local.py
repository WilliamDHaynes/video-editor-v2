"""Prepare one six-minute window locally. Never modifies the source or uses an API."""
import json
import shutil
import subprocess
from pathlib import Path
from settings import ROOT, SOURCE, FFMPEG, FFPROBE

START, LENGTH = 120, 360


def probe(path):
    result = subprocess.run([FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def run(args):
    if shutil.disk_usage(ROOT).free < 3*1024**3:
        raise RuntimeError("Need at least 3 GiB free before preparing another derivative")
    subprocess.run(args, check=True, capture_output=True, timeout=180,
                   creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))


def plan(metadata):
    duration = float(metadata["format"]["duration"])
    if duration < START+LENGTH:
        raise ValueError("This prototype needs a recording at least eight minutes long")
    if not any(s.get("codec_type") == "video" for s in metadata["streams"]):
        raise ValueError("No video stream found")
    tracks = min(3, sum(s.get("codec_type") == "audio" for s in metadata["streams"]))
    if not tracks:
        raise ValueError("This first test needs at least one audio track")
    return duration, tracks


def main():
    if not SOURCE.is_file():
        raise RuntimeError("Set VIDEO_EDITOR_SOURCE to your recording before preparing the sample")
    if (ROOT/"manifest.json").exists() or (ROOT/"sample-frames").exists():
        raise RuntimeError("A sample already exists. Inspect it before replacing local preparation.")
    before = SOURCE.stat()
    metadata = probe(SOURCE)
    duration, tracks = plan(metadata)
    for i in range(tracks):
        target = ROOT/f"DERIVED_sample_source_02m00s-08m00s_audio{i+1}_mono16k.mp3"
        run([FFMPEG, "-nostdin", "-hide_banner", "-v", "error", "-n", "-threads", "1",
             "-ss", str(START), "-i", str(SOURCE), "-t", str(LENGTH), "-map", f"0:a:{i}", "-vn",
             "-c:a", "libmp3lame", "-b:a", "32k", "-ar", "16000", "-ac", "1", "-threads", "1", str(target)])
    frames = ROOT/"sample-frames"
    frames.mkdir()
    for second in range(START, START+LENGTH, 30):
        run([FFMPEG, "-nostdin", "-hide_banner", "-v", "error", "-n", "-hwaccel", "none",
             "-threads", "2", "-ss", str(second), "-i", str(SOURCE), "-map", "0:v:0", "-frames:v", "1",
             "-vf", "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
             "-filter_threads", "1", "-threads", "1", "-q:v", "5", str(frames/f"source_{second:04d}s.jpg")])
    after = SOURCE.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("Source metadata changed during preparation")
    manifest = {"source": str(SOURCE.resolve()), "source_duration_seconds": duration,
                "source_bytes": before.st_size, "source_mtime_ns_after": after.st_mtime_ns,
                "sample_source_start_seconds": START, "sample_source_end_seconds_exclusive": START+LENGTH,
                "prepared_audio_tracks": list(range(tracks)), "source_size_mtime_unchanged": True,
                "audio_track_roles": "Unverified", "local_only": True}
    (ROOT/"source-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (ROOT/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Prepared 12 stills and {tracks} audio track(s) for 02:00-08:00. No uploads or API calls.")


if __name__ == "__main__":
    main()
