"""Visually counterbalanced layouts for new evaluation runs."""

from collections import Counter
from dataclasses import asdict, replace
from itertools import product
from math import sqrt
from random import Random

from .factory import _repair_order, digest, make_task, place_blockers, variable_base
from .geometry import LEGS, WORLD, add, angle_delta, direction, heading, mul, point_segment, trace, verified_trace

CHALLENGE_SEEDS = tuple(range(81602, 81622))
FLIP_FIELDS = {"mirror-angle": "angle", "camera-aim": "yaw", "mirror-width": "length", "add-blocker": "blockers"}


def turn_layout(scene, degrees):
    cos, sin = direction(degrees)

    def turn(point):
        x, y = point
        return (cos*x - sin*y, sin*x + cos*y)

    points = [turn(p) for p in (scene.camera, scene.target, scene.mirror, *scene.ends)]
    span = [max(axis) - min(axis) for axis in zip(*points)]
    scale = min(1, *((limit-38)/extent for extent, limit in zip(span, WORLD)))
    shift = tuple(limit/2 - scale*(min(axis)+max(axis))/2 for axis, limit in zip(zip(*points), WORLD))

    def translated(point):
        return tuple(round(x, 5) for x in add(mul(point, scale), shift))

    return replace(scene, camera=translated(points[0]), target=translated(points[1]),
                   mirror=translated(points[2]), length=round(scene.length*scale, 5),
                   angle=scene.angle+degrees, yaw=scene.yaw+degrees)


def visible_pair(control, base, hit, blocker, rng):
    if control == "camera-aim":
        # Point straight at the target. There is a direct view and no valid reflected view.
        return replace(base, yaw=base.yaw+2), replace(base, yaw=round(heading(base.camera, base.target), 5))
    if control == "add-blocker":
        culprit = verified_trace(blocker).blocked[0][0]
        return replace(blocker, blockers=tuple(b for b in blocker.blockers if b.label != culprit)), blocker
    if control == "mirror-width":
        length = max(base.length, 70)
        offset = (length/2 - 10) * rng.choice((-1, 1))
        center = add(hit, mul(base.tangent, -offset))
        wide = replace(base, mirror=tuple(round(x, 5) for x in center), length=length)
        narrow = replace(wide, length=2*(abs(offset)-8))
        return wide, narrow

    raise ValueError(f"unsupported intervention {control!r}")


def _alternates(base, rejected):
    variants = {-1: [], 1: []}
    for side in variants:
        for offset in range(8, 65, 2):
            scene = replace(base, angle=base.angle+side*offset)
            try:
                check = verified_trace(scene)
            except ValueError as error:
                rejected[str(error)] += 1
                continue
            if len(check.reasons) == 1:
                variants[side].append((scene, check.reasons[0]))
            else:
                rejected["angle did not isolate a failure"] += 1
    return variants


def _candidates(base, alternates, rank, want_flattest, rng):
    lower, upper = ([s for s, _ in alternates[side]] for side in (-1, 1))
    if rank == 1:
        pairs = [(a, b) for a in lower for b in upper]
    else:
        side = upper if rank == 0 else lower
        pairs = [(a, b) for a in side for b in side if b.angle - a.angle >= 4]
    pairs = [p for p in pairs if all(abs(abs(s.angle) - abs(base.angle)) >= 2 for s in p)
             and (abs(base.angle) < min(abs(s.angle) for s in p)) == want_flattest]
    if not pairs:
        raise ValueError("no repair choices at the requested angle rank and apparent tilt")
    return rng.choice(pairs)


def _pair(layout, control, scenes, rng):
    checks = tuple(map(verified_trace, scenes))
    if not checks[0].visible or checks[1].visible or len(checks[1].reasons) != 1:
        raise ValueError("intervention did not change exactly one visibility condition")
    ordered = [(s, "visible" if check.visible else check.reasons[0]) for s, check in zip(scenes, checks)]
    rng.shuffle(ordered)
    return [make_task(layout, control, "visibility", condition, (scene,)) for scene, condition in ordered]


def verify_drift(tasks):
    """Check pose-box corners at ±1 mm and ±1 degree, including blocker clearance."""
    scenes = {scene: check for task in tasks for scene, check in zip(task.scenes, task.checks)}
    allowance = sqrt(2) + 0.5
    for scene, expected in scenes.items():
        expected_geometry = tuple(reason for reason in expected.reasons if reason != "obstructed")
        for cx, cy, tx, ty, mx, my, yaw, angle, width in product((-1, 1), repeat=9):
            moved = replace(scene, camera=add(scene.camera, (cx, cy)), target=add(scene.target, (tx, ty)),
                            mirror=add(scene.mirror, (mx, my)), yaw=scene.yaw+yaw, angle=scene.angle+angle,
                            length=scene.length+width, blockers=())
            check = trace(moved)
            if check.reasons != expected_geometry:
                raise ValueError("fixture drift changes a reference condition")
            if check.hit is None:
                continue
            segments = ((moved.camera, check.hit), (check.hit, moved.target))
            for blocker in scene.blockers:
                for leg, (start, stop) in zip(LEGS, segments):
                    clearance = point_segment(blocker.center, start, stop) - blocker.radius
                    blocked = (blocker.label, leg) in expected.blocked
                    if (clearance if not blocked else -clearance) <= allowance:
                        raise ValueError("fixture drift changes blocker clearance")


def generate_challenge(seed):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be a whole number from 0 to 4294967295")
    rng = Random(seed)
    rejected = Counter()
    cause = "mirror edge miss" if seed % 2 == 0 else "outside field of view"
    control = ("camera-aim", "mirror-width", "add-blocker")[seed % 3]
    rank = (seed // 3) % 3
    # The two extreme ranks can share a working angle only when one has the flatter choice.
    if rank == 2:
        target_first_flat = seed % 2 == 0
        target_second_flat = not target_first_flat
    else:
        target_first_flat = seed % 4 == 0
        target_second_flat = seed % 4 == 2
    for _ in range(320):
        try:
            base = turn_layout(variable_base(rng, cause), rng.choice((-36, -22, -12, 12, 22, 36)))
            hit = verified_trace(base).hit
            if angle_delta(heading(base.camera, base.target), base.yaw) - base.half_fov < 5:
                raise ValueError("visible setup requires a reflected view")
            alternates = _alternates(base, rejected)
            flat_wins = seed % 4 in (0, 1)
            candidates = [(s, reason) for values in alternates.values() for s, reason in values
                          if abs(abs(s.angle) - abs(base.angle)) >= 2 and (abs(base.angle) < abs(s.angle)) == flat_wins]
            if not candidates:
                raise ValueError("no angle-flip candidate at the requested apparent tilt")
            preferred = [(s, reason) for s, reason in candidates if reason == cause]
            failed, _ = rng.choice(preferred or candidates)
            first = place_blockers(base, LEGS[0], rng, rejected)
            second = place_blockers(base, LEGS[1], rng, rejected, verified_trace(first).blocked[0][0])
            order = _repair_order(base, _candidates(base, alternates, rank, target_first_flat, rng), rng)
            other = _repair_order(base, _candidates(base, alternates, (rank+1) % 3, target_second_flat, rng),
                                  rng, order.index(base))
            layout = digest(asdict(base))[:14]
            tasks = _pair(layout, "mirror-angle", (base, failed), rng)
            tasks += _pair(layout, control, visible_pair(control, base, hit, first, rng), rng)
            tasks.extend(make_task(layout, "obstruction-leg", "obstruction", leg, (s,))
                         for s, leg in zip((first, second), LEGS))
            tasks.extend(make_task(layout, "repair-options", "repair", "angle candidates", options) for options in (order, other))
            extras = [(s, r) for values in alternates.values() for s, r in values if s != failed]
            cosmetic, color_condition = (replace(base, angle=base.angle+1), "visible") if seed % 2 else rng.choice(extras)
            if seed % 2 and not verified_trace(cosmetic).visible:
                raise ValueError("cosmetic control needs a distinct visible setting")
            tasks.extend(make_task(layout, "cosmetic", "visibility", color_condition,
                                   (cosmetic,), tint) for tint in (False, True))
            verify_drift(tasks)
            return tasks, dict(sorted(rejected.items()))
        except ValueError as error:
            rejected[str(error)] += 1
    raise RuntimeError(f"seed {seed} exhausted its verified-layout attempts; try another seed")
