"""Attach manually observed camera frames to the exact pilot trials."""

import hashlib
import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps

from .pack import write_json
from .reports import read_json, read_regular

MAX_CAPTURE_BYTES = 12_000_000
MAX_PIXELS = 24_000_000


def stages(task):
    if task.kind == "visibility":
        return ("setup",)
    if task.kind == "obstruction":
        return ("all", "remove-A", "remove-B", "remove-C")
    return task.choices


def _photo_bytes(source):
    data = read_regular(source, MAX_CAPTURE_BYTES)
    try:
        with Image.open(BytesIO(data), formats=("PNG", "JPEG")) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, "is_animated", False):
                raise ValueError("capture must be a single frame under 24 megapixels")
            clean = ImageOps.exif_transpose(image).convert("RGB")
            clean.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            clean.info.clear()
            out = BytesIO()
            clean.save(out, format="PNG")
            return out.getvalue()
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError("invalid capture image") from error


def _safe_chain(*paths):
    if any(path.is_symlink() for path in paths):
        raise ValueError("evidence links must be regular project files")


def record(root, task, stage, observer, visible, source):
    if stage not in stages(task) or visible not in ("YES", "NO"):
        raise ValueError("invalid trial or visibility observation")
    observer = observer.strip()
    if not 1 <= len(observer) <= 48 or not observer.isprintable():
        raise ValueError("observer label must be 1–48 printable characters")
    path = root / task.id
    _safe_chain(root.parent, root, path, path / stage)
    png = _photo_bytes(source)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = path / stage
    if target.exists():
        raise ValueError("a camera frame is already recorded for this trial")
    with TemporaryDirectory(prefix=".capture-", dir=path) as folder:
        staging = Path(folder)
        (staging / "frame.png").write_bytes(png)
        calibration = None
        if (root.parent / "calibration.json").exists():
            from .calibration import measurements

            calibration = measurements(root.parent)
        write_json(staging / "observation.json", {"task_id": task.id, "stage": stage,
                   "observer": observer, "observed": visible, "recorded_utc": datetime.now(UTC).isoformat(),
                   "calibration_sha256": calibration,
                   "sha256": hashlib.sha256(png).hexdigest()})
        os.rename(staging, target)
    return target


def observations(root, task):
    captures = {}
    path = root / task.id
    for stage in stages(task):
        folder = path / stage
        if not folder.exists():
            continue
        readme, image = folder / "observation.json", folder / "frame.png"
        _safe_chain(root.parent, root, path, folder, readme, image)
        if not readme.is_file() or not image.is_file():
            raise ValueError("camera evidence is missing a regular file")
        meta = read_json(readme, limit=8192)
        if (not isinstance(meta, dict) or meta.get("task_id") != task.id or meta.get("stage") != stage
                or meta.get("observed") not in ("YES", "NO") or not isinstance(meta.get("observer"), str)
                or not 1 <= len(meta["observer"]) <= 48 or not meta["observer"].isprintable()):
            raise ValueError("camera evidence has invalid trial details")
        png = read_regular(image, MAX_CAPTURE_BYTES)
        if (not png.startswith(b"\x89PNG\r\n\x1a\n")
                or hashlib.sha256(png).hexdigest() != meta.get("sha256")):
            raise ValueError("camera evidence failed the image integrity check")
        captures[stage] = (meta, png)
    return captures


def camera_result(task, captures):
    if not captures:
        return "Awaiting physical check"
    if set(captures) != set(stages(task)):
        return f"Physical trials recorded · {len(captures)}/{len(stages(task))}"
    observed = {stage: record[0]["observed"] for stage, record in captures.items()}
    if task.kind == "visibility":
        actual = observed["setup"]
    else:
        yes = [letter for letter in task.choices
               if observed[letter if task.kind == "repair" else f"remove-{letter}"] == "YES"]
        already_clear = observed.get("all") == "YES"
        actual = yes[0] if len(yes) == 1 and not already_clear else None
    return "Camera observations agree with the reference" if actual == task.answer else "Camera observations disagree with the reference"
