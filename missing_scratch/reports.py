"""Replay saved replies against a regenerated, hash-checked batch."""

import json
import os
import stat
from pathlib import Path

from .models import score
from .pack import SCHEMA, answer_manifest, task_manifest
from .render import diagram

MAX_REPORT_BYTES = 10_000_000


def _unique_object(entries):
    obj = dict(entries)
    if len(obj) != len(entries):
        raise ValueError("duplicate JSON keys")
    return obj


def _invalid_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def read_regular(path, limit):
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink():
        raise ValueError("Expected a regular file without a symbolic link")
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Expected a regular file within the byte limit")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("File is too large")
    return data


def read_json(path, limit=MAX_REPORT_BYTES):
    data = read_regular(path, limit)
    return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def verify_export(pack, path):
    inputs = path / "inputs"
    reveals = path / "reveals"
    if any(directory.is_symlink() for directory in (path, inputs, reveals)):
        raise ValueError("Run output directories cannot be symbolic links")
    metadata = read_json(path / "answers.json")
    if metadata != json.loads(json.dumps(answer_manifest(pack))):
        raise ValueError("Saved geometry differs from the selected dataset")
    manifest = task_manifest(pack).encode("utf-8")
    if read_regular(inputs / "tasks.jsonl", len(manifest)) != manifest:
        raise ValueError("Saved task manifest differs from the selected dataset")
    for task in pack.tasks:
        filename = f"{task.id}.png"
        png = pack.images[task.id]
        if read_regular(inputs / filename, len(png)) != png:
            raise ValueError("Saved model input differs from the expected PNG")
        reveal = diagram(task, reveal=True)
        if read_regular(reveals / filename, len(reveal)) != reveal:
            raise ValueError("Saved reveal differs from the verified geometry")


def replay(pack, path):
    document = read_json(path)
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or document.get("dataset_id") != pack.id:
        raise ValueError("saved report does not match the regenerated dataset")
    hashes = {task.id: pack.image_hash(task.id) for task in pack.tasks}
    if document.get("image_sha256") != hashes:
        raise ValueError("rendered images differ from the recorded inputs")
    replies, run = document.get("replies"), document.get("run")
    if not isinstance(replies, dict) or not isinstance(run, dict):
        raise ValueError("saved report needs replies and run settings")
    for reply in replies.values():
        if not isinstance(reply, dict) or any(
            value is not None and (not isinstance(value, str) or len(value) > 24000)
            for value in (reply.get(key) for key in ("raw_reply", "error"))
        ):
            raise ValueError("invalid saved reply")
    return score(pack, replies, run)


def display_count(result, pair=False):
    if pair:
        correct, total = result["pair_correct"], result["pair_total"]
    else:
        correct, total = result["correct"], result["total"]
    return f"{correct}/{total} ({correct / total:.1%})" if total else "—"


def markdown(report):
    lines = ["# Benchmark results", "", f"Dataset `{report['dataset_id']}`", "",
             "| Group | Accuracy | Pair accuracy |", "| --- | ---: | ---: |"]
    for label, result in [("Overall", report["summary"]), *report["by_task"].items(), *report["by_control"].items()]:
        lines.append(f"| {label.capitalize()} | {display_count(result)} | {display_count(result, pair=True)} |")
    lines += ["", "A pair earns credit when both answers are correct.", "", "## Reply outcomes", ""]
    lines += [f"- {status.replace('_', ' ').capitalize()} · {count}"
              for status, count in report["summary"]["statuses"].items()]
    v = report["visibility_outcomes"]
    lines += ["", "## Inspection visibility", "", f"- False passes · {v['false_pass']}/{v['hidden_cases']} hidden cases",
              f"- False rejects · {v['false_reject']}/{v['visible_cases']} visible cases",
              f"- Manual review · {v['manual_review']}/{v['visibility_cases']} visibility cases"]
    lines += ["", "## Task results", "", "| Task ID | Expected | Parsed | Outcome |", "| --- | --- | --- | --- |"]
    lines += [f"| `{r['id']}` | {r['expected']} | {r['parsed'] or '—'} | {r['status']} |" for r in report["rows"]]
    return "\n".join(lines) + "\n"
