"""Generate, validate and export an auditable batch of model inputs."""

import hashlib
import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from .challenge import CHALLENGE_SEEDS, FLIP_FIELDS, generate_challenge
from .factory import HELDOUT_SEEDS, PILOT_SEED, Task, digest, generate
from .render import diagram

SCHEMA = 1


@dataclass(frozen=True)
class Pack:
    suite: str
    seeds: tuple[int, ...]
    tasks: tuple[Task, ...]
    images: dict[str, bytes]
    rejections: dict[int, dict[str, int]]

    @property
    def id(self):
        return digest([SCHEMA, self.suite, self.seeds,
                       [(t.id, t.question, t.answer) for t in self.tasks]])

    def image_hash(self, task_id):
        return hashlib.sha256(self.images[task_id]).hexdigest()


def pairs(tasks):
    grouped = defaultdict(list)
    for task in tasks:
        grouped[task.pair].append(task)
    return dict(grouped)


def validate_pairs(tasks):
    if len({t.id for t in tasks}) != len(tasks):
        raise ValueError("duplicate task IDs")
    for group in pairs(tasks).values():
        if len(group) != 2:
            raise ValueError("each pair needs two members")
        first, second = group
        if first.control in FLIP_FIELDS:
            name = FLIP_FIELDS[first.control]
            a, b = first.scenes[0], second.scenes[0]
            if getattr(a, name) == getattr(b, name) or replace(a, **{name: getattr(b, name)}) != b or first.answer == second.answer or first.tinted != second.tinted:
                raise ValueError(f"{first.control} pair must change only {name} and flip the answer")
            if name == "blockers" and len(set(a.blockers) ^ set(b.blockers)) != 1:
                raise ValueError("add-blocker pair must change one obstruction")
        if first.control == "cosmetic":
            if first.scenes != second.scenes or first.answer != second.answer or first.tinted == second.tinted:
                raise ValueError("cosmetic pair must preserve geometry and answer")
        if first.control == "obstruction-leg":
            if first.condition == second.condition or first.answer == second.answer:
                raise ValueError("obstruction pair must change the blocked leg and its label")


def make_pack(suite="pilot", seed=None, *, legacy_sandbox=False):
    if suite == "sandbox" and seed is not None:
        if seed in (*HELDOUT_SEEDS, *CHALLENGE_SEEDS, PILOT_SEED):
            raise ValueError("this seed is reserved for the pilot or held-out suite")
        seeds = (seed,)
    elif suite in ("pilot", "heldout", "challenge") and seed is None:
        seeds = {"pilot": (PILOT_SEED,), "heldout": HELDOUT_SEEDS, "challenge": CHALLENGE_SEEDS}[suite]
    else:
        raise ValueError("use a seed only with the sandbox suite")
    tasks, rejections = [], {}
    for layout_seed in seeds:
        if suite == "challenge" or (suite == "sandbox" and not legacy_sandbox):
            batch, rejected = generate_challenge(layout_seed)
        else:
            batch, rejected = generate(layout_seed, pilot=suite == "pilot")
        tasks.extend(batch)
        rejections[layout_seed] = rejected
    validate_pairs(tasks)
    if len({t.layout for t in tasks}) != len(seeds):
        raise ValueError("duplicate layouts in suite")
    images = {task.id: diagram(task) for task in tasks}
    if suite == "challenge" or (suite == "sandbox" and not legacy_sandbox):
        if len({(images[t.id], t.question) for t in tasks}) != len(tasks):
            raise ValueError("the corrected suite contains duplicate model inputs")
    return Pack(suite, seeds, tuple(tasks), images, rejections)


def write_json(path, value):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.close()
            os.link(staged, path)
        finally:
            staged.unlink(missing_ok=True)


def task_manifest(pack):
    return "".join(json.dumps({"id": task.id, "image": f"{task.id}.png", "question": task.question,
                               "sha256": pack.image_hash(task.id)}, ensure_ascii=False) + "\n" for task in pack.tasks)


def answer_manifest(pack):
    return {"schema": SCHEMA, "dataset_id": pack.id, "suite": pack.suite, "seeds": pack.seeds,
            "layout_count": len(pack.seeds), "rejected_candidates": pack.rejections,
            "tasks": [asdict(task) for task in pack.tasks]}


def export_pack(pack, path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True)
    inputs = path / "inputs"
    inputs.mkdir()
    reveals = path / "reveals"
    reveals.mkdir()
    for task in pack.tasks:
        name = f"{task.id}.png"
        (inputs / name).write_bytes(pack.images[task.id])
        (reveals / name).write_bytes(diagram(task, reveal=True))
    (inputs / "tasks.jsonl").write_bytes(task_manifest(pack).encode("utf-8"))
    write_json(path / "answers.json", answer_manifest(pack))
