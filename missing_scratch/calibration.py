"""Bind new benchmark runs to measured fixture and camera observations."""

from dataclasses import replace
from datetime import datetime
from math import isfinite
from pathlib import Path

from .factory import PILOT_SEED, digest, generate
from .geometry import verified_trace
from .reports import read_json

EVIDENCE_ROOT = Path(__file__).resolve().parents[1] / "evidence"


def measurements(root):
    if root.is_symlink():
        raise ValueError("Evidence directory cannot be a symbolic link")
    document = read_json(root / "calibration.json", limit=8192)
    if not isinstance(document, dict) or type(document.get("schema")) is not int or document["schema"] != 1:
        raise ValueError("Invalid calibration record")
    for field in ("observer", "recorded_utc", "camera_settings", "repeat_notes"):
        value = document.get(field)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 400 or not value.isprintable():
            raise ValueError(f"Record measured fixture details for {field}")
    try:
        recorded = datetime.fromisoformat(document["recorded_utc"])
    except ValueError as error:
        raise ValueError("Record an ISO date and time with timezone for the calibration") from error
    if recorded.utcoffset() is None:
        raise ValueError("Calibration timestamp needs a timezone")

    def number(value):
        if type(value) not in (int, float) or not isfinite(value) or abs(value) > 1000:
            raise ValueError("Calibration measurements must be finite numbers within the fixture scale")
        return value

    def two(key):
        pair = document.get(key)
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"Record two measurements for {key}")
        return tuple(map(number, pair))

    camera, target, mirror = (two(key) for key in ("camera_mm", "target_mm", "mirror_center_mm"))
    angles = two("mirror_angles_deg")
    scale = number(document.get("printed_bar_mm"))
    yaw = number(document.get("camera_yaw_deg"))
    half_fov = number(document.get("horizontal_fov_deg")) / 2
    width = number(document.get("mirror_width_mm"))
    lens = number(document.get("lens_height_mm"))
    target_height = number(document.get("target_height_mm"))
    if abs(scale - 50) > 1 or not 0 < min(lens, target_height) or abs(lens-target_height) > 1:
        raise ValueError("Recheck printed scale and align the camera and red X heights")
    pilot, _ = generate(PILOT_SEED, pilot=True)
    for task, angle in zip(pilot[:2], angles):
        nominal = task.scenes[0]
        measured = replace(nominal, camera=camera, target=target, mirror=mirror, angle=angle,
                           yaw=yaw, half_fov=half_fov, length=width)
        if any(abs(a-b) > 2 for actual, planned in ((camera, nominal.camera), (target, nominal.target), (mirror, nominal.mirror))
               for a, b in zip(actual, planned)) or any(abs(a-b) > 2 for a, b in (
                   (angle, nominal.angle), (yaw, nominal.yaw), (half_fov, nominal.half_fov), (width, nominal.length))):
            raise ValueError("Measured pilot geometry falls outside the tabletop alignment targets")
        if verified_trace(measured).visible != (task.answer == "YES"):
            raise ValueError("Measured fixture changes the reference outcome")
    return digest(document)


def verified_calibration(root=EVIDENCE_ROOT):
    from .evidence import camera_result, observations

    try:
        calibration = measurements(root)
    except FileNotFoundError as error:
        raise ValueError("Camera calibration is pending. Record the measured fixture first.") from error
    pilot, _ = generate(PILOT_SEED, pilot=True)
    completed = {"visibility": 0, "obstruction": 0, "repair": 0}
    hashes = {}
    raw_labels = {}
    for task in pilot:
        frames = observations(root / "captures", task)
        if any(meta.get("calibration_sha256") != calibration for meta, _ in frames.values()):
            raise ValueError("A camera frame is linked to a different calibration record")
        for stage, (meta, _) in frames.items():
            before = raw_labels.setdefault(meta["sha256"], meta["observed"])
            if before != meta["observed"]:
                raise ValueError("The same camera frame has contradictory observations")
            yes = stage in (f"remove-{task.answer}", task.answer) or (stage == "setup" and task.answer == "YES")
            if (meta["observed"] == "YES") != yes:
                raise ValueError("A camera observation disagrees with the reference. Resolve the discrepancy before scoring.")
        result = camera_result(task, frames)
        if result == "Camera observations agree with the reference":
            completed[task.kind] += 1
            hashes[task.id] = {stage: meta["sha256"] for stage, (meta, _) in frames.items()}
    if completed["visibility"] != 2 or not (completed["obstruction"] and completed["repair"]):
        raise ValueError("Camera evidence is pending for both flagship settings, a blocker trial, or a repair trial.")
    return digest([calibration, hashes])
