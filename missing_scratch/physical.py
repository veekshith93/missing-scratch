"""A full-size fixture template for the six pilot tasks."""

from io import BytesIO

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from .factory import PILOT_SEED, generate
from .geometry import WORLD, add, direction, mul
from .render import BLUE, GRID, INK, MUTED, RED, TEAL, label, line, plus


def point(x, y):
    return x * mm, y * mm


def copy(pdf, y, text, size=10, color=INK, bold=False):
    label(pdf, *point(14.5, y), text, size, color, bold)


def fixture(pdf, title, note, scenes, names):
    w, h = WORLD
    scene = scenes[0]
    copy(pdf, 14, title, 22, INK, True)
    copy(pdf, 22, note, 10, MUTED)

    def project(p):
        return point(14.5+p[0], 179-p[1])

    a, b = project((0, h)), project((w, 0))
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(0.7)
    pdf.rect(*a, b[0]-a[0], b[1]-a[1], fill=0, stroke=1)
    for x in range(0, w, 10):
        line(pdf, project((x, 0)), project((x, h)), GRID, 0.25)
        if x % 20 == 0:
            label(pdf, *project((x, -4)), str(x), 7, MUTED, centered=True)
    for y in range(0, h, 10):
        line(pdf, project((0, y)), project((w, y)), GRID, 0.25)
        if y % 20 == 0:
            label(pdf, *project((-6, y-1)), str(y), 7, MUTED, centered=True)

    plus(pdf, project(scene.camera), 2*mm, INK, 1.4)
    plus(pdf, project(scene.target), 2*mm, RED, 1.4, diagonal=True)
    label(pdf, *project(add(scene.camera, (-11, -7))), "Lens", 10, INK, True)
    label(pdf, *project(add(scene.target, (-11, -7))), "Red X", 10, RED, True)
    start, aim_point = (add(scene.camera, mul(direction(scene.yaw), distance)) for distance in (5, 48))
    line(pdf, project(start), project(aim_point), BLUE, 1, (4, 2))
    label(pdf, *project(add(aim_point, (-7, 4))), "Aim", 9, BLUE, True)

    for i, (variant, name) in enumerate(zip(scenes, names)):
        color = (TEAL, BLUE, RED)[i]
        dash = (None, (5, 2), (2, 2))[i]
        left, right = variant.ends
        line(pdf, project(left), project(right), color, 1.6, dash)
        for end in (left, right):
            plus(pdf, project(end), 1*mm, color, 0.8)
        label(pdf, *project(add(right, (3, -1.2))), f"{name} ({variant.angle:+g} deg)", 8.5, color, True)
    plus(pdf, project(scene.mirror), 1*mm, INK, 1)
    side = add(scene.mirror, (0, 22))
    label(pdf, *project(side), "Reflective face toward lens and X", 9, TEAL, True, True)

    for disk in scene.blockers:
        pdf.setStrokeColor("#88522B")
        pdf.setLineWidth(1)
        pdf.circle(*project(disk.center), disk.radius*mm, stroke=1, fill=0)
        label(pdf, *project(add(disk.center, (0, -1.2))), disk.label, 10, INK, True, True)

    line(pdf, point(14.5, 194), point(64.5, 194), INK, 1.3)
    for x in (14.5, 64.5):
        line(pdf, point(x, 192), point(x, 196), INK, 1)
    label(pdf, *point(69, 195), "50 mm calibration bar", 9, INK, True)
    label(pdf, *point(142, 195), "A4 landscape. Print at 100% / Actual Size.", 10, INK, True)
    label(pdf, *point(142, 201), "Grid lines are 10 mm apart. Mirror length is 62 mm.", 9, MUTED)
    pdf.showPage()


def print_kit():
    tasks, _ = generate(PILOT_SEED, pilot=True)
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=landscape(A4), bottomup=0, invariant=True)
    pdf.setTitle("The Missing Scratch | tabletop pilot")
    fixture(pdf, "The Missing Scratch | tabletop pilot",
            f"Visibility 1  {tasks[0].id}     Visibility 2  {tasks[1].id}",
            (tasks[0].scenes[0], tasks[1].scenes[0]), ("1", "2"))
    for index, task in enumerate(tasks[2:], 1):
        fixture(pdf, f"{task.kind.capitalize()} | pilot {1 + (index-1) % 2}",
                f"Task {task.id}. Keep the camera lens and the center of the red X fixed.",
                task.scenes, ("Fixed",) if task.kind == "obstruction" else tuple("ABC"))

    copy(pdf, 15, "Run the tabletop check", 23, INK, True)
    steps = (
        ("1. Verify the print scale", "Measure the 50 mm bar. Use Actual Size on A4 landscape and check again if the bar differs."),
        ("2. Fix the camera and part", "Center the lens and a small red X over their marks. Set both at the same height. Point the camera along Aim."),
        ("3. Place the upright mirror", "Align the reflective face to the marked line. Use exactly 62 mm of reflective width and mask any extra width."),
        ("4. Capture each setting", "Keep the camera fixed. Decide if the center of the X appears inside the mirror. Save the full frame."),
        ("5. Check obstruction and repair", "Use opaque upright cylinders on the marked circles. Capture with all objects, then remove each in turn."),
    )
    for i, (heading, description) in enumerate(steps):
        y = 33 + i*18
        copy(pdf, y, heading, 11, INK, True)
        copy(pdf, y+6, description, 10, MUTED)
    copy(pdf, 117, "Capture repair settings A, B and C separately. Record discrepancies and repeat before adjusting the fixture.", 10, MUTED)
    copy(pdf, 124, "Observation log", 15, INK, True)
    copy(pdf, 132, "Observer _____________________   Date __________   Lens height ______ mm   Scale measured ______ mm", 10)
    for i, task in enumerate(tasks):
        y = 145 + i*8
        copy(pdf, y, f"{task.kind.capitalize()}   {task.id}", 9.5)
        label(pdf, *point(100, y), "Observed __________________   Capture filename(s) ____________________________", 9.5)
    copy(pdf, 202, "Keep this sheet separate from the blind diagram check. See the README to attach captures to task IDs.", 9, MUTED)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
