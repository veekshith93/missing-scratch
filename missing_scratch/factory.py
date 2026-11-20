"""Seeded tasks with controlled pairs and independently verified labels."""

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from random import Random

from .geometry import LEGS, Blocker, Scene, Trace, add, angle_delta, heading, mul, sub, trace, verified_trace

PILOT_SEED = 2026
HELDOUT_SEEDS = (43020, 77499, 16422, 89649)
QUESTIONS = {
    "visibility": "Can the camera see the red X in the mirror?",
    "obstruction": "Which labeled object blocks the reflected view of the red X?",
    "repair": "Which mirror setting restores the camera’s view of the red X?",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Task:
    id: str
    layout: str
    pair: str
    control: str
    kind: str
    condition: str
    scenes: tuple[Scene, ...]
    checks: tuple[Trace, ...]
    choices: tuple[str, ...]
    answer: str
    tinted: bool = False

    @property
    def question(self):
        return QUESTIONS[self.kind]


def make_task(layout, control, kind, condition, scenes, tinted=False):
    checks = tuple(map(verified_trace, scenes))
    choices = ("YES", "NO") if kind == "visibility" else tuple("ABC")
    if kind == "repair":
        if len(scenes) != 3 or len({round(s.angle, 6) for s in scenes}) != 3:
            raise ValueError("repair needs three distinct settings")
        if any(replace(s, angle=scenes[0].angle) != scenes[0] for s in scenes):
            raise ValueError("repair changes more than mirror angle")
        if sum(c.visible for c in checks) != 1 or any(len(c.reasons) > 1 for c in checks):
            raise ValueError("repair needs one unambiguous working setting")
        answer = choices[next(i for i, check in enumerate(checks) if check.visible)]
    elif kind == "obstruction":
        if len(scenes) != 1 or set(b.label for b in scenes[0].blockers) != set(choices):
            raise ValueError("obstruction needs three labeled objects")
        check = checks[0]
        if check.reasons != ("obstructed",) or len(check.blocked) != 1:
            raise ValueError("obstruction needs a unique causal object on one leg")
        answer = check.blocked[0][0]
        if not verified_trace(replace(scenes[0], blockers=tuple(b for b in scenes[0].blockers if b.label != answer))).visible:
            raise ValueError("removing blocker fails to restore visibility")
    else:
        if kind != "visibility" or len(scenes) != 1 or len(checks[0].reasons) > 1:
            raise ValueError("visibility needs one scene with at most one failure")
        answer = choices[not checks[0].visible]

    pair = digest([layout, control, kind])[:14]
    task_id = digest({"pair": pair, "scenes": [asdict(s) for s in scenes], "tinted": tinted})[:16]
    return Task(task_id, layout, pair, control, kind, condition, scenes, checks, choices, answer, tinted)


def aim(scene):
    hit = trace(scene).hit
    if hit is None:
        raise ValueError("camera or target behind mirror")
    aimed = replace(scene, yaw=round(heading(scene.camera, hit), 5))
    if angle_delta(heading(aimed.camera, aimed.target), aimed.yaw) - aimed.half_fov < 5:
        raise ValueError("target falls near direct camera view")
    if not verified_trace(aimed).visible:
        raise ValueError("base mirror must be visible")
    return aimed


def hidden_settings(base, cause, rejected):
    accepted = {-1: [], 1: []}
    for side in accepted:
        for delta in range(8, 55, 2):
            moved = replace(base, angle=base.angle + side * delta)
            try:
                check = verified_trace(moved)
            except ValueError as error:
                rejected[str(error)] += 1
                continue
            if check.reasons == (cause,):
                accepted[side].append(moved)
            else:
                rejected["alternate angle did not isolate requested failure"] += 1
    if not all(accepted.values()):
        raise ValueError("no single-cause alternates on both sides")
    return accepted


def place_blockers(base, leg, rng, rejected, skip=None):
    hit = verified_trace(base).hit
    start, end = (base.camera, hit) if leg == LEGS[0] else (hit, base.target)
    for _ in range(96):
        labels = rng.sample(list("ABC"), 3)
        if labels[0] == skip:
            continue
        center = add(start, mul(sub(end, start), rng.uniform(0.36, 0.65)))
        centers = [tuple(round(x, 2) for x in center)]
        centers.extend((rng.randint(20, 248), rng.randint(16, 134)) for _ in range(2))
        radii = [rng.randint(7, 10), rng.randint(6, 9), rng.randint(6, 9)]
        candidate = replace(base, blockers=tuple(Blocker(label, point, radius)
                                                  for label, point, radius in zip(labels, centers, radii)))
        try:
            if verified_trace(candidate).blocked == ((labels[0], leg),):
                return candidate
            rejected["decoy or second leg intersected"] += 1
        except ValueError as error:
            rejected[str(error)] += 1
    raise ValueError("could not place a distinct blocker")


def pilot_base():
    return aim(Scene((52, 29), 45, 26, (216, 35), (135, 106), 62, 0))


def variable_base(rng, cause):
    camera = (rng.randint(35, 60), rng.randint(21, 35))
    target = (rng.randint(205, 237), rng.randint(24, 44))
    mirror = (rng.randint(127, 145), rng.randint(94, 115))
    angle = rng.randint(-8, 8)
    if rng.randrange(2):
        camera, target, mirror = tuple((268 - x, y) for x, y in (camera, target, mirror))
        angle = -angle
    narrow = cause == "outside field of view"
    length = rng.randint(96, 112) if narrow else rng.randint(48, 69)
    half = rng.randint(9, 12) if narrow else rng.randint(24, 30)
    return aim(Scene(camera, 45, half, target, mirror, length, angle))


def _repair_order(base, failed, rng, previous_index=None):
    choices = [base, *failed]
    rng.shuffle(choices)
    if choices.index(base) == previous_index:
        choices = choices[1:] + choices[:1]
    return tuple(choices)


def generate(seed: int, pilot: bool = False):
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be a whole number from 0 to 4294967295")
    rng = Random(seed)
    rejected = Counter()
    cause = "mirror edge miss" if pilot or seed % 2 == 0 else "outside field of view"
    for _ in range(100):
        try:
            base = pilot_base() if pilot else variable_base(rng, cause)
            alternates = hidden_settings(base, cause, rejected)
            first = place_blockers(base, LEGS[0], rng, rejected)
            blocked = (first, place_blockers(base, LEGS[1], rng, rejected, verified_trace(first).blocked[0][0]))
            break
        except ValueError as error:
            if pilot:
                raise
            rejected[str(error)] += 1
    else:
        raise RuntimeError("scene generation exhausted its verified-layout attempts")

    layout = digest(asdict(base))[:14]
    flip_sign = 1 if pilot or seed % 4 in (0, 1) else -1
    choices = alternates[flip_sign]
    hidden = choices[2 if pilot else rng.randrange(len(choices))]
    visibility = (base, hidden) if pilot or rng.randrange(2) else (hidden, base)
    tasks = [make_task(layout, "mirror-angle", "visibility", "visible" if s == base else cause, (s,)) for s in visibility]
    tasks.extend(make_task(layout, "obstruction-leg", "obstruction", leg, (s,)) for leg, s in zip(LEGS, blocked))

    order = _repair_order(base, (alternates[-1][0], alternates[1][0]), rng)
    second = _repair_order(base, (alternates[-1][-1], alternates[1][-1]), rng, order.index(base))
    tasks.extend(make_task(layout, "repair-options", "repair", cause, variants) for variants in (order, second))
    if not pilot:
        control = base if seed % 2 else alternates[-flip_sign][0]
        if seed % 2:
            for delta in (2, -2, 1, -1):
                candidate = replace(base, angle=base.angle + delta)
                try:
                    if verified_trace(candidate).visible:
                        control = candidate
                        break
                except ValueError as error:
                    rejected[str(error)] += 1
        condition = "visible" if seed % 2 else cause
        tasks.extend(make_task(layout, "cosmetic", "visibility", condition, (control,), tinted) for tinted in (False, True))
    return tasks, dict(sorted(rejected.items()))
