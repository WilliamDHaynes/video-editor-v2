"""Bounded, evidence-first editorial selection. No model calls on import."""
import copy
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from settings import SOURCE, FFMPEG, source_duration
START, END = 120, 480
MAX_CANDIDATES = 3
REPORT = ROOT / "editorial" / "review.json"
CAUTION = "Stills can miss rapid events; transcript times identify chunks, not exact words. Review source video and sound."


def save_report(report, path=None):
    path = path or REPORT
    path.parent.mkdir(exist_ok=True, parents=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def empty_report():
    return {
        "schema_version": 2, "mode": "real", "run_id": None,
        "source_name": SOURCE.name, "source_url": "/source-video",
        "source_duration": source_duration(),
        "window": {"start": START, "end": END}, "status": "awaiting_analysis",
        "verdict": "pending", "rationale": "No real transcript or editorial judgment has been generated.",
        "uncertainty": [CAUTION], "audio_track": None, "audio_role_verified": False,
        "transcript": [
            {"id": f"t{i+1:02}", "start": s, "end": min(s+30, END),
             "text": None, "origin": "pending", "timing_precision": "30-second chunk"}
            for i, s in enumerate(range(START, END, 30))
        ],
        "frames": [
            {"id": f"f{i+1:02}", "timestamp": s, "tier": "coarse",
             "path": f"sample-frames/source_{s:04d}s.jpg", "width": 640, "height": 360,
             "available": (ROOT/f"sample-frames/source_{s:04d}s.jpg").is_file()}
            for i, s in enumerate(range(START, END, 30))
        ],
        "candidates": [], "stages": [], "review_decisions": {},
    }


def load_report():
    return json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else empty_report()


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite timestamp")
    return float(value)


def phrase(value, label, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Missing or overlong {label}")
    return value.strip()


def validate_judgment(payload, report, phase, allowed_intervals=None):
    """Reject invented references/quotes, invalid ranges and quota-driven responses."""
    if not isinstance(payload, dict):
        raise ValueError("Editorial result must be an object")
    verdict = payload.get("verdict")
    if verdict not in ("candidates", "reject_all", "uncertain"):
        raise ValueError("Editorial result must allow candidates, reject_all or uncertain")
    rationale = phrase(payload.get("rationale"), "overall rationale")
    uncertainties = payload.get("uncertainty")
    if not isinstance(uncertainties, list) or not uncertainties or len(uncertainties) > 8:
        raise ValueError("Uncertainty must be explicit")
    uncertainties = [phrase(x, "uncertainty", 800) for x in uncertainties]
    raw = payload.get("candidates")
    if not isinstance(raw, list) or len(raw) > MAX_CANDIDATES:
        raise ValueError("At most three candidates are allowed")
    if (verdict == "reject_all" and raw) or (verdict == "candidates" and not raw):
        raise ValueError("Verdict and candidate count disagree")
    transcripts = {t["id"]: t for t in report["transcript"]}
    frames = {f["id"]: f for f in report["frames"]}
    output = []
    previous_end = report["window"]["start"]
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("Candidate must be an object")
        start, end = number(item.get("start")), number(item.get("end"))
        lo, hi = report["window"]["start"], report["window"]["end"]
        if not lo <= start < end <= hi or not 8 <= end-start <= 60 or start < previous_end:
            raise ValueError("Candidate must be chronological, nonoverlapping and 8-60 seconds within the analyzed window")
        if allowed_intervals and not any(a <= start < end <= b for a, b in allowed_intervals):
            raise ValueError("Dense review cannot introduce an uninspected interval")
        previous_end = end
        context = {"start": max(lo, start-10), "end": min(hi, end+10)}
        if allowed_intervals:
            a, b = next((a, b) for a, b in allowed_intervals if a <= start < end <= b)
            context = {"start": a, "end": b}
        kind = item.get("kind")
        if kind not in ("humor", "action", "commentary", "interesting", "other"):
            raise ValueError("Unknown editorial kind")
        confidence = item.get("confidence")
        if confidence not in ("low", "medium", "high"):
            raise ValueError("Confidence must be low, medium or high")
        uncertain = item.get("uncertainty")
        if not isinstance(uncertain, list) or not uncertain or len(uncertain) > 8:
            raise ValueError("Candidate uncertainty is required")
        uncertain = [phrase(x, "candidate uncertainty", 800) for x in uncertain]
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 12:
            raise ValueError("Candidate requires supporting evidence")
        checked = []
        for e in evidence:
            if not isinstance(e, dict):
                raise ValueError("Evidence must reference transcript or frame data")
            ref = e.get("ref")
            if e.get("kind") == "transcript":
                t = transcripts.get(ref)
                quote = phrase(e.get("quote"), "verbatim dialogue", 2000)
                if not t or t["text"] is None or quote not in t["text"]:
                    raise ValueError("Dialogue quote is not present in the referenced transcript")
                if t["end"] <= context["start"] or t["start"] >= context["end"]:
                    raise ValueError("Dialogue evidence is outside candidate context")
                checked.append({"kind": "transcript", "ref": ref, "quote": quote,
                                "start": t["start"], "end": t["end"],
                                "timing_precision": t["timing_precision"]})
            elif e.get("kind") == "frame":
                f = frames.get(ref)
                if not f or not context["start"] <= f["timestamp"] < context["end"]:
                    raise ValueError("Visual evidence is unknown or outside candidate context")
                checked.append({"kind": "frame", "ref": ref, "timestamp": f["timestamp"],
                                "observation": phrase(e.get("observation"), "visual observation", 1200)})
            else:
                raise ValueError("Loudness/motion scores alone are not editorial evidence")
        output.append({
            "id": f"c{i+1:02}", "start": start, "end": end, "context": context,
            "title": phrase(item.get("title"), "title", 100), "kind": kind,
            "setup": phrase(item.get("setup"), "setup", 1200),
            "change": phrase(item.get("change"), "change", 1200),
            "payoff": phrase(item.get("payoff"), "payoff", 1200),
            "rationale": phrase(item.get("rationale"), "reason to watch", 2000),
            "confidence": confidence, "uncertainty": uncertain,
            "evidence": checked, "phase": phase, "source_review_required": True,
        })
    return {"verdict": verdict, "rationale": rationale,
            "uncertainty": list(dict.fromkeys(uncertainties + [CAUTION])), "candidates": output}


def dense_plan(candidates):
    """At most 32 stills/candidate, 96 total; include context before and after."""
    timestamps = set()
    for candidate in candidates:
        a, b = candidate["context"]["start"], candidate["context"]["end"]
        step = max(1, math.ceil((b-a)/31))
        values = [a + i*step for i in range(32) if a+i*step < b]
        if values and b-values[-1] > 1 and len(values) < 32:
            values.append(b-0.1)
        timestamps.update(round(t, 3) for t in values)
    return sorted(timestamps)


def extract_dense(report, run_dir, report_progress):
    timestamps = dense_plan(report["candidates"])
    frames = []
    for i, seconds in enumerate(timestamps):
        if shutil.disk_usage(ROOT).free < 3*1024**3:
            raise RuntimeError("Less than 3 GiB free; dense sampling stopped")
        target = run_dir / f"dense_{int(round(seconds*1000)):07d}ms.jpg"
        subprocess.run(
            [FFMPEG, "-nostdin", "-hide_banner", "-v", "error", "-n",
             "-hwaccel", "none", "-threads", "2", "-ss", str(seconds),
             "-i", str(SOURCE), "-map", "0:v:0", "-frames:v", "1",
             "-vf", "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2", "-filter_threads", "1", "-threads", "1",
             "-q:v", "5", str(target)], check=True, capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        frames.append({"id": f"d{i+1:03}", "timestamp": seconds, "tier": "dense",
                       "path": target.relative_to(ROOT).as_posix(), "width": 640, "height": 360})
        if i % 8 == 0:
            report_progress(f"Inspecting candidate context: {i+1}/{len(timestamps)} stills")
    return frames


def selection_pipeline(report, gateway, dense_loader, persist, progress):
    """Injection points permit zero-network fixture tests of the actual orchestration."""
    report["status"] = "coarse_review"; persist(report)
    progress("Checking dialogue and coarse visual evidence; reject-all is allowed")
    coarse = validate_judgment(gateway.judge(report, "coarse"), report, "coarse")
    report.update(coarse)
    report["stages"].append({"phase": "coarse", **copy.deepcopy(coarse)})
    persist(report)
    if not coarse["candidates"]:
        report["status"] = "complete"; persist(report)
        progress("Selection complete: " + coarse["verdict"])
        return report
    contexts = [(c["context"]["start"], c["context"]["end"]) for c in coarse["candidates"]]
    report["status"] = "dense_sampling"; persist(report)
    report["frames"].extend(dense_loader(report))
    report["status"] = "dense_review"; persist(report)
    progress("Checking denser context for setup, change and payoff")
    refined = validate_judgment(gateway.judge(report, "dense"), report, "dense", contexts)
    report.update(refined)
    report["stages"].append({"phase": "dense", **copy.deepcopy(refined)})
    report["status"] = "complete"; persist(report)
    progress("Selection complete: review proposed ranges in the source" if report["candidates"]
             else "Selection complete: " + report["verdict"])
    return report


def set_review(report, candidate_id, decision, start, end, note, source_reviewed):
    if report.get("mode") != "real" or report.get("status") != "complete":
        raise ValueError("Only completed real analysis can be reviewed")
    if decision not in ("keep", "reject", "uncertain"):
        raise ValueError("Unknown review decision")
    candidate = next((c for c in report["candidates"] if c["id"] == candidate_id), None)
    if not candidate:
        raise ValueError("Unknown candidate")
    start, end = number(start), number(end)
    if not candidate["context"]["start"] <= start < end <= candidate["context"]["end"]:
        raise ValueError("Edited boundaries must stay within inspected context")
    if decision == "keep" and (source_reviewed is not True or report["verdict"] != "candidates"):
        raise ValueError("Keep requires source review and a supported candidate verdict")
    if decision == "keep":
        for other_id, other in report["review_decisions"].items():
            if other_id != candidate_id and other["decision"] == "keep" and start < other["end"] and end > other["start"]:
                raise ValueError("Kept ranges must not overlap")
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("Review note is too long")
    report["review_decisions"][candidate_id] = {
        "decision": decision, "start": start, "end": end, "note": note,
        "source_reviewed": source_reviewed is True,
        "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return report


def reviewed_ranges(report):
    if report.get("mode") != "real":
        raise ValueError("Fixtures cannot become real edits")
    return [
        {"candidate_id": c["id"], "title": c["title"], **report["review_decisions"][c["id"]]}
        for c in report["candidates"]
        if report["review_decisions"].get(c["id"], {}).get("decision") == "keep"
        and report["review_decisions"][c["id"]].get("source_reviewed")
    ]


def fixture_report(kind):
    """Intentionally synthetic text and visuals. Never associated with the actual recording."""
    if kind not in ("candidates", "reject_all", "uncertain"):
        raise ValueError("Unknown fixture")
    report = {
        "schema_version": 2, "mode": "fixture", "run_id": "fixture-" + kind,
        "source_name": "SYNTHETIC EDITORIAL FIXTURE", "source_url": None,
        "source_duration": 90, "window": {"start": 0, "end": 90},
        "status": "complete", "audio_track": None, "audio_role_verified": False,
        "transcript": [
            {"id": "t01", "start": 0, "end": 30,
             "text": "FICTIONAL TEST DIALOGUE: This crate definitely fits through the door.",
             "origin": "fixture", "timing_precision": "synthetic 30-second chunk"},
            {"id": "t02", "start": 30, "end": 60,
             "text": "FICTIONAL TEST DIALOGUE: That was the wrong door. We carried it in a circle.",
             "origin": "fixture", "timing_precision": "synthetic 30-second chunk"},
            {"id": "t03", "start": 60, "end": 90,
             "text": "FICTIONAL TEST DIALOGUE: Waiting here for the lift.",
             "origin": "fixture", "timing_precision": "synthetic 30-second chunk"},
        ],
        "frames": [
            {"id": "f01", "timestamp": 0, "tier": "coarse", "path": "fixtures/frame-door.svg", "width": 640, "height": 360},
            {"id": "f02", "timestamp": 30, "tier": "coarse", "path": "fixtures/frame-loop.svg", "width": 640, "height": 360},
            {"id": "f03", "timestamp": 60, "tier": "coarse", "path": "fixtures/frame-wait.svg", "width": 640, "height": 360},
        ],
        "candidates": [], "stages": [], "review_decisions": {},
    }
    candidate = {
        "start": 12, "end": 48, "title": "A confident plan becomes a circular trip",
        "kind": "humor", "setup": "The fictional speaker confidently says the crate will fit.",
        "change": "The next fictional line reveals the wrong door was used.",
        "payoff": "The speaker admits the crate was carried in a circle.",
        "rationale": "A short expectation and reversal could form a self-contained joke in this synthetic example.",
        "confidence": "medium", "uncertainty": ["Synthetic fixture only; this dialogue did not come from real footage."],
        "evidence": [
            {"kind": "transcript", "ref": "t01", "quote": "This crate definitely fits through the door."},
            {"kind": "transcript", "ref": "t02", "quote": "That was the wrong door. We carried it in a circle."},
            {"kind": "frame", "ref": "f02", "observation": "The diagram illustrates returning to the starting point."},
        ],
    }
    if kind == "reject_all":
        report["transcript"] = [
            {**t, "text": "FICTIONAL TEST DIALOGUE: Still waiting. No change yet."}
            for t in report["transcript"]
        ]
    payload = {
        "verdict": kind,
        "rationale": {
            "candidates": "Synthetic demonstration of a timecoded, evidence-backed proposal.",
            "reject_all": "No worthy moment in this synthetic window: waiting repeats without a meaningful change or payoff.",
            "uncertain": "Synthetic evidence is too incomplete to decide; inspect context instead of forcing a clip.",
        }[kind],
        "uncertainty": ["FIXTURE: all dialogue, judgments and diagrams are invented for software testing."],
        "candidates": [candidate] if kind == "candidates" else [],
    }
    report.update(validate_judgment(payload, report, "fixture"))
    return report
