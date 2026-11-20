"""Planar specular reflection, with an independent Fermat-path cross-check."""

from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, isfinite, radians, sin, sqrt

Vec = tuple[float, float]
WORLD = (268, 150)
LEGS = ("camera leg", "target leg")
MIRROR_MARGIN_MM = 4.0
FOV_MARGIN_DEG = 3.0
OBSTACLE_MARGIN_MM = 2.5
SIDE_MARGIN_MM = 6.0


def add(a: Vec, b: Vec) -> Vec:
    return a[0] + b[0], a[1] + b[1]


def sub(a: Vec, b: Vec) -> Vec:
    return a[0] - b[0], a[1] - b[1]


def mul(v: Vec, scale: float) -> Vec:
    return v[0] * scale, v[1] * scale


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def direction(angle: float) -> Vec:
    a = radians(angle)
    return cos(a), sin(a)


def heading(a: Vec, b: Vec) -> float:
    dx, dy = sub(b, a)
    return degrees(atan2(dy, dx))


def distance(a: Vec, b: Vec) -> float:
    return hypot(*sub(a, b))


def angle_delta(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def point_segment(point: Vec, start: Vec, end: Vec) -> float:
    ray = sub(end, start)
    length_sq = dot(ray, ray)
    if length_sq == 0:
        return distance(point, start)
    t = max(0.0, min(1.0, dot(sub(point, start), ray) / length_sq))
    return distance(point, add(start, mul(ray, t)))


@dataclass(frozen=True)
class Blocker:
    label: str
    center: Vec
    radius: float


@dataclass(frozen=True)
class Scene:
    camera: Vec
    yaw: float
    half_fov: float
    target: Vec
    mirror: Vec
    length: float
    angle: float
    blockers: tuple[Blocker, ...] = ()

    @property
    def tangent(self) -> Vec:
        return direction(self.angle)

    @property
    def normal(self) -> Vec:
        x, y = self.tangent
        return y, -x

    @property
    def ends(self) -> tuple[Vec, Vec]:
        half = mul(self.tangent, self.length / 2)
        return sub(self.mirror, half), add(self.mirror, half)


@dataclass(frozen=True)
class Trace:
    hit: Vec | None
    reasons: tuple[str, ...]
    blocked: tuple[tuple[str, str], ...] = ()
    mirror_mm: float | None = None
    fov_deg: float | None = None
    obstacle_mm: float | None = None
    side_mm: float = 0.0

    @property
    def visible(self) -> bool:
        return not self.reasons


def trace(scene: Scene) -> Trace:
    """Compute a mirror hit by projecting toward the virtual image point."""
    n = scene.normal
    sc = dot(sub(scene.camera, scene.mirror), n)
    st = dot(sub(scene.target, scene.mirror), n)
    if min(sc, st) <= 0:
        return Trace(None, ("mirror backside",), side_mm=min(sc, st))

    virtual = sub(scene.target, mul(n, 2 * st))
    hit = add(scene.camera, mul(sub(virtual, scene.camera), sc / (sc + st)))
    u = dot(sub(hit, scene.mirror), scene.tangent)
    mirror_mm = scene.length / 2 - abs(u)
    fov_deg = scene.half_fov - angle_delta(heading(scene.camera, hit), scene.yaw)
    legs = ((scene.camera, hit), (hit, scene.target))
    clearances = [(b.label, leg, point_segment(b.center, a, z) - b.radius)
                  for b in scene.blockers for leg, (a, z) in zip(LEGS, legs)]
    hits = tuple((label, leg) for label, leg, clearance in clearances if clearance <= 0)
    reasons = tuple(reason for failed, reason in ((mirror_mm < 0, "mirror edge miss"),
                                                   (fov_deg < 0, "outside field of view"),
                                                   (bool(hits), "obstructed")) if failed)
    closest = min((abs(clearance) for _, _, clearance in clearances), default=None)
    return Trace(hit, reasons, hits, mirror_mm, fov_deg, closest, min(sc, st))


def circle_crossing(a: Vec, b: Vec, disk: Blocker) -> bool:
    """Independently check segment/circle intersection with a quadratic."""
    ray, offset = sub(b, a), sub(a, disk.center)
    aa = dot(ray, ray)
    bb = 2 * dot(ray, offset)
    cc = dot(offset, offset) - disk.radius**2
    if cc <= 0 or dot(sub(b, disk.center), sub(b, disk.center)) <= disk.radius**2:
        return True
    discriminant = bb**2 - 4 * aa * cc
    if discriminant < 0 or aa == 0:
        return False
    root = sqrt(discriminant)
    return any(0 <= t <= 1 for t in ((-bb - root) / (2 * aa), (-bb + root) / (2 * aa)))


def fermat(scene: Scene) -> tuple[Vec | None, tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Minimize total physical path length along the infinite mirror line."""
    tangent, normal = scene.tangent, scene.normal
    c, x = sub(scene.camera, scene.mirror), sub(scene.target, scene.mirror)
    uc, ux = dot(c, tangent), dot(x, tangent)
    dc, dx = dot(c, normal), dot(x, normal)
    if dc <= 0 or dx <= 0:
        return None, ("mirror backside",), ()
    low, high = sorted((uc, ux))
    for _ in range(48):
        mid = (low + high) / 2
        slope = (mid - uc) / hypot(mid - uc, dc) + (mid - ux) / hypot(mid - ux, dx)
        if slope > 0:
            high = mid
        else:
            low = mid
    u = (low + high) / 2
    hit = add(scene.mirror, mul(tangent, u))
    ray = sub(hit, scene.camera)
    forward = dot(ray, direction(scene.yaw)) / hypot(*ray)
    blocked = tuple((b.label, leg) for b in scene.blockers
                    for leg, segment in zip(LEGS, ((scene.camera, hit), (hit, scene.target)))
                    if circle_crossing(*segment, b))
    reasons = tuple(reason for failed, reason in ((abs(u) > scene.length / 2, "mirror edge miss"),
                                                   (forward < cos(radians(scene.half_fov)), "outside field of view"),
                                                   (bool(blocked), "obstructed")) if failed)
    return hit, reasons, blocked


def _inside(p: Vec, margin: float) -> bool:
    return all(margin <= coordinate <= limit - margin for coordinate, limit in zip(p, WORLD))


def check_layout(scene: Scene) -> None:
    points = (scene.camera, scene.target, scene.mirror)
    if any(not isinstance(point, (list, tuple)) or len(point) != 2 for point in points):
        raise ValueError("Camera, mirror and target require two coordinates")
    values = (*scene.camera, *scene.target, *scene.mirror, scene.angle, scene.yaw, scene.length, scene.half_fov)
    if not all(type(v) in (int, float) and isfinite(v) for v in values) or not 24 <= scene.length <= 122 or not 8 <= scene.half_fov <= 40:
        raise ValueError("invalid dimensions")
    if distance(scene.camera, scene.target) < 20 or not all(_inside(p, 6) for p in (*scene.ends, scene.camera, scene.target)):
        raise ValueError("layout outside drawing or coincident positions")
    if len(scene.blockers) > 3 or len({b.label for b in scene.blockers}) != len(scene.blockers):
        raise ValueError("invalid blocker labels")
    for index, b in enumerate(scene.blockers):
        if (not isinstance(b.center, (tuple, list)) or len(b.center) != 2
                or any(type(v) not in (int, float) or not isfinite(v) for v in (*b.center, b.radius))):
            raise ValueError("Blocker center and radius must be finite numbers")
        if (b.label not in "ABC" or len(b.label) != 1 or not 4 <= b.radius <= 15 or not _inside(b.center, b.radius + 3)
                or min(distance(b.center, scene.camera), distance(b.center, scene.target),
                       point_segment(b.center, *scene.ends)) < b.radius + 4):
            raise ValueError("blocker intersects another component or leaves the drawing")
        if any(distance(b.center, other.center) < b.radius + other.radius + 4 for other in scene.blockers[:index]):
            raise ValueError("blockers overlap")


def verified_trace(scene: Scene) -> Trace:
    check_layout(scene)
    main = trace(scene)
    if abs(main.side_mm) < SIDE_MARGIN_MM:
        raise ValueError("reflective side margin")
    for value, minimum, label in ((main.mirror_mm, MIRROR_MARGIN_MM, "mirror edge margin"),
                                  (main.fov_deg, FOV_MARGIN_DEG, "field of view margin"),
                                  (main.obstacle_mm, OBSTACLE_MARGIN_MM, "blocker clearance margin")):
        if value is not None and abs(value) < minimum:
            raise ValueError(label)
    hit, reasons, blocked = fermat(scene)
    if reasons != main.reasons or blocked != main.blocked or (hit is None) != (main.hit is None):
        raise RuntimeError("reflection solvers disagree")
    if hit is not None and distance(hit, main.hit) > 0.000001:
        raise RuntimeError("reflection hit points disagree")
    return main
