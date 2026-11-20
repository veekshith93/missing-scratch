"""Export a self-contained browser demo from verified benchmark tasks."""

import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .challenge import generate_challenge
from .factory import PILOT_SEED
from .pack import make_pack
from .physical import print_kit
from .render import diagram, explain
from .reports import replay

ARCHIVE_RUNS = (
    ("GPT-6.2 Sol", "Image and question", "heldout-vision"),
    ("GPT-6.1 Terra", "Image and question", "heldout-terra"),
    ("GPT-6.2 Sol", "Text only", "heldout-text"),
)


def data_uri(media_type, value):
    return f"data:{media_type};base64,{base64.b64encode(value).decode('ascii')}"


def exercise(task, image=None):
    return {"id": task.id, "kind": task.kind, "question": task.question, "choices": task.choices,
            "answer": task.answer, "explanation": explain(task),
            "diagram": data_uri("image/png", image if image is not None else diagram(task)),
            "reveal": data_uri("image/png", diagram(task, reveal=True))}


def demo_data(root):
    pilot = make_pack("pilot")
    groups = []

    def add_pair(name, seed, tasks, images):
        if len(tasks) != 2 or tasks[0].pair != tasks[1].pair:
            raise ValueError(f"Expected a verified pair for {name}")
        groups.append({"name": name, "seed": seed,
                       "tasks": [exercise(task, images.get(task.id)) for task in tasks]})

    add_pair("Flagship pair", PILOT_SEED, pilot.tasks[:2], pilot.images)
    add_pair("Obstruction", PILOT_SEED, pilot.tasks[2:4], pilot.images)
    corrected = {seed: generate_challenge(seed)[0] for seed in (81603, 81604, 81605)}
    for title, seed, control in (("Repair", 81603, "repair-options"), ("Camera aim", 81603, "camera-aim"),
                                  ("Mirror width", 81604, "mirror-width"), ("Add a blocker", 81605, "add-blocker"),
                                  ("Color control", 81605, "cosmetic")):
        add_pair(title, seed, [task for task in corrected[seed] if task.control == control], {})

    pack = make_pack("heldout")
    results, example = [], None
    for model, mode, folder in ARCHIVE_RUNS:
        report = replay(pack, root / "output" / folder / "report.json")
        summary = report["summary"]
        safety = report["visibility_outcomes"]
        results.append({"model": model, "input": mode, "right": summary["correct"], "total": summary["total"],
                        "pairs": summary["pair_correct"], "pair_total": summary["pair_total"],
                        "false_passes": safety["false_pass"], "hidden": safety["hidden_cases"]})
        if folder == "heldout-terra":
            row = next(r for r in report["rows"] if r["condition"] == "outside field of view" and r["status"] == "incorrect")
            task = next(t for t in pack.tasks if t.id == row["id"])
            example = {**exercise(task, pack.images[task.id]), "reply": report["replies"][task.id]["raw_reply"]}
    return {"pairs": groups, "results": results, "example": example, "printKit": data_uri("application/pdf", print_kit())}


def export_prototype(source_root, output):
    template = Path(__file__).with_name("prototype.html").read_text(encoding="utf-8")
    for tag in ("style", "script"):
        content = template.split(f"<{tag}>", 1)[1].split(f"</{tag}>", 1)[0]
        fingerprint = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
        template = template.replace(f"@@{tag.upper()}_HASH@@", fingerprint)
    data = json.dumps(demo_data(source_root), ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as stream:
        staged = Path(stream.name)
        try:
            stream.write(template.replace("@@PAYLOAD@@", data))
            stream.close()
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)
    return output
