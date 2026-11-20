"""Run isolated model requests and score the exact replies."""

import json
import os
import re
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import monotonic

from .pack import SCHEMA, pairs
from .factory import digest
from .journal import checkpoint as open_checkpoint

MODELS = ("gpt-6.2-sol", "gpt-6.1-terra")
EFFORT = "low"
TIMEOUT = 95
STATUSES = ("correct", "incorrect", "parse_error", "request_error", "missing_reply")
CODEX_FLAGS = (
    "--json", "--color", "never", "--ephemeral", "--ignore-user-config", "--ignore-rules",
    "--sandbox", "read-only", "--skip-git-repo-check", "--disable", "memories",
    "--disable", "plugins", "--disable", "apps", "--disable", "shell_tool",
    "--disable", "image_generation", "--disable", "multi_agent",
    "--enable", "skip_host_skill_discovery", "-c", 'web_search="disabled"',
    "-c", "mcp_servers={}", "-c", "project_doc_max_bytes=0", "-c", 'approval_policy="never"',
)
CODEX_ENV = ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "USER", "LOGNAME", "LANG", "LC_ALL", "SYSTEMROOT")


def prompt_for(task):
    format_hint = "Yes or No" if task.kind == "visibility" else "A, B, or C"
    return f"{task.question}\nReply with a single answer ({format_hint})."


def parse_answer(raw, choices):
    if not isinstance(raw, str):
        return None
    match = re.fullmatch(r"(YES|NO|A|B|C)[.]?", raw.strip(), re.ASCII | re.IGNORECASE)
    answer = match[1].upper() if match else None
    return answer if answer in choices else None


def codex_events(stdout, code):
    try:
        if len(stdout) > 1_000_000:
            raise ValueError("oversize event stream")
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        items = [event["item"] for event in events if event["type"].startswith("item.")]
        messages = [event["item"]["text"] for event in events
                    if event["type"] == "item.completed" and event["item"]["type"] == "agent_message"]
        if any(not isinstance(message, str) for message in messages):
            raise ValueError("invalid reply")
        activity = sorted({item["type"] for item in items if item["type"] not in ("agent_message", "reasoning", "error")})
    except (AttributeError, ValueError, KeyError, TypeError):
        return {"error": "Unexpected Codex event stream"}

    reply = {"raw_reply": "\n".join(messages) if messages else None, "tool_item_types": activity}
    if reply["raw_reply"] and len(reply["raw_reply"]) > 24_000:
        return {"error": "Model reply exceeded the record limit", "tool_item_types": activity}
    completed = [event for event in events if event["type"] == "turn.completed"]
    if activity:
        return {**reply, "error": "Tool activity observed in model turn"}
    if code or len(completed) != 1 or any(event["type"] in ("error", "turn.failed") for event in events):
        return {**reply, "error": f"Codex turn failed (exit {code})"}
    usage = completed[0].get("usage")
    reply["usage"] = {name: count for name, count in usage.items() if type(count) is int} if isinstance(usage, dict) else None
    return reply


def codex_completion(model, prompt, png):
    if model not in MODELS:
        raise ValueError("unsupported model")
    started = monotonic()
    with TemporaryDirectory(prefix="missing-scratch-eval-") as folder:
        cmd = ["codex", "exec", *CODEX_FLAGS, "-m", model, "-c", f'model_reasoning_effort="{EFFORT}"']
        if png is not None:
            (Path(folder) / "input.png").write_bytes(png)
            cmd.extend(("--image", "input.png"))
        cmd.extend(("--", "-"))
        env = {name: os.environ[name] for name in CODEX_ENV if name in os.environ}
        try:
            process = subprocess.run(cmd, cwd=folder, input=prompt, text=True, encoding="utf-8", errors="replace",
                                     env=env, capture_output=True, timeout=TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            reply = {"error": "Codex turn timed out"}
        except OSError as error:
            reply = {"error": type(error).__name__}
        else:
            reply = codex_events(process.stdout, process.returncode)
    return {**reply, "seconds": round(monotonic() - started, 3)}


def _summary(rows, paired):
    statuses = {status: sum(row["status"] == status for row in rows) for status in STATUSES}
    right = statuses["correct"]
    both = sum(pair["correct"] for pair in paired)
    return {"correct": right, "total": len(rows), "accuracy": right / len(rows) if rows else None,
            "pair_correct": both, "pair_total": len(paired), "pair_accuracy": both / len(paired) if paired else None,
            "statuses": statuses}


def visibility_outcomes(rows):
    visibility = [row for row in rows if row["kind"] == "visibility"]
    hidden = sum(r["expected"] == "NO" for r in visibility)
    visible = len(visibility) - hidden
    false_pass = sum(r["status"] == "incorrect" and r["expected"] == "NO" for r in visibility)
    false_reject = sum(r["status"] == "incorrect" and r["expected"] == "YES" for r in visibility)
    review = sum(r["status"] in ("parse_error", "request_error", "missing_reply") for r in visibility)
    return {"false_pass": false_pass, "hidden_cases": hidden, "false_pass_rate": false_pass / hidden if hidden else None,
            "false_reject": false_reject, "visible_cases": visible, "false_reject_rate": false_reject / visible if visible else None,
            "manual_review": review, "visibility_cases": len(visibility)}


def score(pack, replies, run):
    task_ids = {t.id for t in pack.tasks}
    if set(replies) - task_ids:
        raise ValueError("replies contain unknown task IDs")
    rows, by_id = [], {}
    for task in pack.tasks:
        reply = replies.get(task.id, {})
        raw = reply.get("raw_reply")
        parsed = parse_answer(raw, task.choices)
        if reply.get("error"):
            status = "request_error"
        elif task.id not in replies:
            status = "missing_reply"
        elif parsed is None:
            status = "parse_error"
        else:
            status = "correct" if parsed == task.answer else "incorrect"
        row = {"id": task.id, "kind": task.kind, "condition": task.condition, "pair": task.pair,
               "control": task.control, "expected": task.answer, "parsed": parsed, "status": status}
        rows.append(row)
        by_id[task.id] = row
    paired = [{"id": key, "kind": group[0].kind, "control": group[0].control,
               "members": [t.id for t in group], "correct": all(by_id[t.id]["status"] == "correct" for t in group)}
              for key, group in pairs(pack.tasks).items()]
    partitions = {}
    for name, subsets in (("task", {row["kind"] for row in rows}), ("control", {row["control"] for row in rows})):
        key = "kind" if name == "task" else "control"
        partitions[name] = {item: _summary([row for row in rows if row[key] == item],
                                            [pair for pair in paired if pair[key] == item]) for item in sorted(subsets)}
    grouped = defaultdict(list)
    for row in rows:
        grouped[f"{row['kind']} / {row['condition']}"].append(row)
    return {"schema": SCHEMA, "dataset_id": pack.id, "suite": pack.suite, "seeds": pack.seeds,
            "image_sha256": {t.id: pack.image_hash(t.id) for t in pack.tasks}, "run": run,
            "summary": _summary(rows, paired), "by_task": partitions["task"], "by_control": partitions["control"],
            "by_condition": {key: _summary(grouped[key], []) for key in sorted(grouped)},
            "visibility_outcomes": visibility_outcomes(rows), "rows": rows, "pairs": paired, "replies": replies}


def evaluate(pack, model, mode, jobs=1, progress=None, *, checkpoint=None, resume=False, request_limit=None, calibration=None):
    if model not in MODELS or mode not in ("vision", "text-only") or not 1 <= jobs <= 4:
        raise ValueError("unsupported evaluation settings")
    version = subprocess.run(["codex", "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    run = {"model": model, "mode": mode, "backend": version, "reasoning_effort": EFFORT,
           "timeout_seconds": TIMEOUT, "jobs": jobs,
           "order_seed": 9821, "temperature": "provider default", "input_policy": "question and answer format; one PNG for vision"}
    if calibration:
        run["calibration_evidence_sha256"] = calibration
    order = list(pack.tasks)
    Random(run["order_seed"]).shuffle(order)

    def request(task):
        png = pack.images[task.id] if mode == "vision" else None
        return task.id, codex_completion(model, prompt_for(task), png)

    identity = digest([pack.id, run, [(t.id, pack.image_hash(t.id), prompt_for(t)) for t in pack.tasks]])
    local = {}
    log = (open_checkpoint(checkpoint, identity, {t.id for t in pack.tasks}, resume) if checkpoint is not None
           else nullcontext((local, local.__setitem__, datetime.now(UTC).isoformat())))
    with log as (replies, record, started):
        pending = [task for task in order if task.id not in replies][:request_limit]
        workers = ThreadPoolExecutor(max_workers=jobs)
        try:
            futures = [workers.submit(request, task) for task in pending]
            for finished in as_completed(futures):
                task_id, reply = finished.result()
                record(task_id, reply)
                if progress:
                    progress(task_id, reply.get("error"))
        finally:
            workers.shutdown(cancel_futures=True)
    run["started_utc"] = started
    return score(pack, replies, run)
