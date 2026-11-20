"""Render scaled diagrams and keep the ray overlays on separate images."""

from contextlib import closing
from io import BytesIO
from threading import Lock

import pypdfium2
from reportlab.pdfgen.canvas import Canvas

from .geometry import WORLD, add, direction, mul

INK = "#142736"
MUTED = "#4B6373"
TEAL = "#11756C"
RED = "#AD2934"
BLUE = "#46758F"
GRID = "#D9E4E9"
WHITE = "#FFFFFF"
LETTERS = "ABC"
PDFIUM_LOCK = Lock()


def label(pdf, x, y, copy, size=10, color=INK, bold=False, centered=False):
    pdf.setFillColor(color)
    pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    draw = pdf.drawCentredString if centered else pdf.drawString
    draw(x, y, copy)


def line(pdf, a, b, color, width=1.2, dash=None):
    pdf.setStrokeColor(color)
    pdf.setLineWidth(width)
    pdf.setDash(*dash) if dash else pdf.setDash()
    pdf.line(*a, *b)
    pdf.setDash()


def polygon(pdf, points, fill):
    path = pdf.beginPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.close()
    pdf.setFillColor(fill)
    pdf.drawPath(path, fill=1, stroke=0)


def plus(pdf, point, size, color, width=1.2, diagonal=False):
    x, y = point
    if diagonal:
        line(pdf, (x-size, y-size), (x+size, y+size), color, width)
        line(pdf, (x-size, y+size), (x+size, y-size), color, width)
    else:
        line(pdf, (x-size, y), (x+size, y), color, width)
        line(pdf, (x, y-size), (x, y+size), color, width)


def draw_scene(pdf, scene, origin, scale, tinted=False, reveal=None):
    """The origin is the lower-left world coordinate on a top-down canvas."""
    left, bottom = origin
    w, h = WORLD
    project = lambda point: (left + scale * point[0], bottom - scale * point[1])
    pdf.saveState()
    clip = pdf.beginPath()
    clip.rect(left, bottom-h*scale, w*scale, h*scale)
    pdf.clipPath(clip, stroke=0, fill=0)
    pdf.setFillColor("#F1F8F2" if tinted else "#FCFDFE")
    pdf.rect(left, bottom-h*scale, w*scale, h*scale, stroke=0, fill=1)

    camera = project(scene.camera)
    rays = tuple(project(add(scene.camera, mul(direction(scene.yaw + delta), 600)))
                 for delta in (-scene.half_fov, 0, scene.half_fov))
    polygon(pdf, (camera, rays[0], rays[1], rays[2]), "#E7F2FA")
    for x in range(0, w, 20):
        line(pdf, project((x, 0)), project((x, h)), GRID, 0.35)
    for y in range(0, h, 20):
        line(pdf, project((0, y)), project((w, y)), GRID, 0.35)
    for boundary in (rays[0], rays[2]):
        line(pdf, camera, boundary, BLUE, 0.9, (3.5, 2.5))

    if reveal is not None and reveal.hit is not None:
        if "mirror edge miss" in reveal.reasons:
            a = add(scene.mirror, mul(scene.tangent, -220))
            b = add(scene.mirror, mul(scene.tangent, 220))
            line(pdf, project(a), project(b), TEAL, 0.8, (3, 3))
        hit = project(reveal.hit)
        color = TEAL if reveal.visible else RED
        dash = None if reveal.visible else (4, 2)
        line(pdf, camera, hit, color, 2.4, dash)
        line(pdf, hit, project(scene.target), color, 2.4, dash)
        pdf.setFillColor(color)
        pdf.circle(*hit, 3.1, stroke=0, fill=1)

    for blocker in scene.blockers:
        px, py = project(blocker.center)
        blocked = reveal is not None and any(label == blocker.label for label, _ in reveal.blocked)
        pdf.setFillColor("#FFE1D5" if blocked else "#FFEDCF")
        pdf.setStrokeColor(RED if blocked else "#7C532B")
        pdf.setLineWidth(1.6 if blocked else 1.15)
        pdf.circle(px, py, blocker.radius*scale, fill=1, stroke=1)
        label(pdf, px, py+3.8, blocker.label, 11, RED if blocked else "#5B3B1E", True, True)

    line(pdf, *map(project, scene.ends), TEAL, 3.8)
    for fraction in (-0.38, -0.19, 0, 0.19, 0.38):
        point = add(scene.mirror, mul(scene.tangent, scene.length*fraction))
        line(pdf, project(point), project(add(point, mul(scene.normal, 4))), TEAL, 1.25)

    toward = direction(scene.yaw)
    cx, cy = camera
    pdf.setFillColor(INK)
    pdf.roundRect(cx-6, cy-4.2, 12, 8.4, 1.5, stroke=0, fill=1)
    pivot = add(scene.camera, mul(toward, 20))
    line(pdf, camera, project(pivot), INK, 1.4)
    arrow = [project(pivot), *(project(add(pivot, mul(direction(scene.yaw+180+turn), 5)))
                               for turn in (-31, 31))]
    polygon(pdf, arrow, INK)
    label(pdf, cx, cy+18, "Camera", 10, INK, True, True)

    x, y = project(scene.target)
    pdf.setFillColor(WHITE)
    pdf.setStrokeColor("#B4C8D3")
    pdf.setLineWidth(0.9)
    pdf.roundRect(x-7.5, y-7.5, 15, 15, 2, stroke=1, fill=1)
    plus(pdf, (x, y), 4.8, RED, 2.2, diagonal=True)
    label(pdf, x, y+18, "Marked part", 10, RED, True, True)
    pdf.restoreState()
    pdf.setStrokeColor("#B4C8D3")
    pdf.setLineWidth(0.8)
    pdf.rect(left, bottom-h*scale, w*scale, h*scale, stroke=1, fill=0)


def legend(pdf, x, y):
    line(pdf, (x, y-3), (x+21, y-3), BLUE, 1.1, (4, 3))
    label(pdf, x+28, y, "Camera field of view", 10, MUTED)
    line(pdf, (x+151, y-3), (x+175, y-3), TEAL, 3)
    line(pdf, (x+163, y-3), (x+163, y+3), TEAL, 1.2)
    label(pdf, x+182, y, "Ticks face the reflective side", 10, MUTED)
    return x+336


def explain(task):
    if task.kind == "repair":
        return f"Setting {task.answer} is the only one with a clear reflection inside the camera’s view."
    check = task.checks[0]
    if task.kind == "obstruction":
        leg = check.blocked[0][1]
        segment = "camera and mirror" if leg == "camera leg" else "mirror and target"
        return f"Object {task.answer} intersects the light path between the {segment}."
    if check.visible:
        return "The reflection hits the mirror inside the camera’s field of view and both legs are clear."
    if "mirror edge miss" in check.reasons:
        return f"The reflection point is {abs(check.mirror_mm):.1f} mm beyond the mirror’s edge."
    if "outside field of view" in check.reasons:
        return f"The reflection hits the mirror {abs(check.fov_deg):.1f}° outside the camera’s field of view."
    return "The camera and target must be on the mirror’s reflective side."


def raster_pdf(data, scale=2):
    # Streamlit can render from several session threads. PDFium requires serialized native calls.
    with (PDFIUM_LOCK, closing(pypdfium2.PdfDocument(data)) as document,
          closing(document[0]) as page, closing(page.render(scale=scale, rev_byteorder=True)) as bitmap):
        im = bitmap.to_pil().convert("RGB")
        out = BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()


def diagram(task, reveal=False):
    repair = task.kind == "repair"
    width, height = (670, 772) if repair else (620, 410)
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=(width, height), bottomup=0, invariant=True)
    label(pdf, 29, 34, f"Reference answer  {task.answer.title()}" if reveal else
          "Mirror settings" if repair else "Inspection setup", 23, INK, True)
    label(pdf, 29, 57, explain(task) if reveal else
          "Same scale and fixed camera. Use the center of the red X." if repair else
          "Top view to scale. Use the center of the red X.", 11, MUTED)
    if repair:
        for index, scene in enumerate(task.scenes):
            y = 81 + 217 * index
            label(pdf, 30, y+22, f"Setting {LETTERS[index]}", 13, INK, True)
            if reveal:
                check = task.checks[index]
                label(pdf, 30, y+41, "Visible" if check.visible else "Hidden", 10, TEAL if check.visible else RED, True)
                if not check.visible:
                    reason = check.reasons[0]
                    label(pdf, 30, y+56, "Outside view" if reason == "outside field of view" else reason.capitalize(), 9, MUTED)
            draw_scene(pdf, scene, (144, y+198), 1.32, task.tinted, task.checks[index] if reveal else None)
    else:
        draw_scene(pdf, task.scenes[0], (54, 363), 1.9, task.tinted, task.checks[0] if reveal else None)
    y = height-20
    rhs = legend(pdf, 30, y)
    if reveal:
        label(pdf, rhs, y, "Solid clear path / dashed failed path", 10, MUTED)
    else:
        bar = (1.32 if repair else 1.9)*20
        line(pdf, (rhs, y-4), (rhs+bar, y-4), MUTED, 1.4)
        label(pdf, rhs+bar+9, y, "20 mm", 9.5, MUTED)
    pdf.save()
    return raster_pdf(buffer.getvalue(), 1.8 if repair else 2)
