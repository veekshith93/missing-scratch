# Validation evidence

| Check | Status |
| --- | --- |
| Independent solvers | Each exported task passed both the virtual-image and stationary-path solvers. |
| Known answers and margins | Tests cover a visible reflection, finite-edge misses, outside-view hits, wrong reflective side, tangencies and ambiguous repairs. |
| Fixture sensitivity | The automated pilot test perturbs camera, target, mirror and blocker positions by up to 1 mm per axis and yaw and mirror angle by up to 1° across 120 draws per scene. Labels held through the tested perturbations. |
| Repeatability | The seed sweep covers 513 sandbox seeds. Replay checks image hashes and recomputes scores from raw replies. |
| Browser demo | Chrome checks covered both flagship reveals, saved and live model predictions, PDF download, fresh layouts, result inspection and a 390 px viewport. Two browser sessions generated ten fresh layouts after the renderer fix. |
| Security checks | Tests exercise model input isolation, tool-call rejection, timeouts, task-ID binding, tampered reports, malformed and oversized inputs, evidence path traversal and capture integrity. The 35 resolved Python runtime distributions in `constraints.txt` were checked with `pip-audit` on November 20, 2026. The scan found no known vulnerabilities. |
| Blind teammate answers | Awaiting a teammate. |
| Physical camera captures | Awaiting tabletop assembly and capture. |

Browser testing exposed a crash during concurrent diagram generation. The renderer now serializes native PDFium calls, and a regression test verifies 48 renders across eight threads. [PDFium threading requirements](https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading)

## Blind diagram check

Send a teammate the PNGs and questions from [`output/pilot/inputs`](output/pilot/inputs) in a mixed order. Ask them to save each ID, their answer and the visual evidence behind it before opening a reveal. Then compare with `answers.json`. If a teammate needs fixture dimensions or an explanation that the model never sees, record the issue against the ID. Review all six before scaling the physical sample.

| Task ID | Teammate answer | Evidence they used | Diagram issue |
| --- | --- | --- | --- |
| | | | |

## Recreate the tabletop pilot

Print the [tabletop kit](output/print/mirror-setup.pdf) on A4 landscape at **Actual Size**. Verify the 50 mm bar with a ruler. Use a phone camera on a stand, a small plane mirror with 62 mm of usable width, a part with a small red X, and opaque cylinders for the obstruction trials.

1. Put the lens and X directly over their marks at the same height. Face the marked part toward the mirror and fix the camera’s aim along the printed direction. Keep the lens, zoom and orientation fixed across captures.
2. Keep the mirror upright and align its reflective plane with line `1`. Capture the full camera frame. Keep the camera and part fixed, rotate the mirror to line `2` and capture again. Judge visibility only within the mirror outline.
3. For obstruction, start with all three cylinders. Then remove one at a time and replace it before removing the next. For repair, capture A, B and C in the order printed. Record deviations between fixtures and diagrams, including mirror width, alignment and camera angle.

Copy `calibration.example.json` to `evidence/calibration.json` and enter the measured values before attaching frames. Use the grid’s origin and millimetre axes for camera lens, target and mirror pivot positions. Measure horizontal field of view at the fixed zoom and crop used for all captures. At a known distance along the optical axis, measure the visible width on a plane perpendicular to the axis and compute `2 × atan(width / (2 × distance))` in degrees. The nominal pilot field is 52°. If needed, set a fixed crop that matches the diagram and record it in the settings. Note how you repeated the setup and use a timestamp with a timezone.

The calibration check compares the measured coordinates, width, yaw, field of view and both mirror angles with the pilot and reruns the geometry. It checks linked captures from both flagship settings, a complete blocker trial and a complete repair trial. If a recorded frame disagrees, keep the evidence and resolve the discrepancy before scoring. Run the check with this command.

```sh
.venv/bin/python -m missing_scratch check-calibration
```

Attach each actual camera frame with the observed visibility. The example below labels the frame `YES` when the observer sees the red X in the mirror. Record the outcome you actually see, including disagreements.

```sh
.venv/bin/python -m missing_scratch record \
  --task d6516c647688895a --stage setup --observer "Teammate initials" \
  --visible YES --capture /path/to/camera-frame.jpg
```

Stage names are `setup` for visibility, `all` and `remove-A`/`remove-B`/`remove-C` for obstruction, and `A`/`B`/`C` for repair. Use the task ID printed on the template. The app displays the attached frames under **Answer reveal**. The observation remains partial until each required stage is recorded. The recorder sanitizes normal PNG/JPEG frames by re-encoding them, removes metadata and stores captures in the git-ignored evidence folder. Preserve original frames separately and get the observers’ permission before sharing evidence.

## Finish the first-round package

Add the blind review and physical captures with their task IDs. Record the demo and prepare the deck using the organizer’s template. Check the participant portal for the required links and fields before submitting. [Organizer walkthrough at the submission section](https://www.youtube.com/watch?v=X6lTYulY04M&t=1846s)

The two sign-offs separate the hackathon evidence from a partner pilot on real production parts. [Pre-release and pilot checks](PRE_RELEASE.md)
