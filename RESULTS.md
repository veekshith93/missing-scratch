# Recorded model results

These runs use the archived pilot and original held-out suites. The corrected suite has 200 tasks and its live evaluation is awaiting calibrated camera evidence. The validation checks and shortcut baselines are recorded separately. [Corrected suite checks](PRE_RELEASE.md)

GPT-6.1 Terra answered all 16 obstruction and repair tasks correctly and missed four of the 16 visibility tasks. The misses include a ray that passes beyond a mirror edge and a ray that hits the mirror outside the camera’s field of view. GPT-6.2 Sol answered all 32 diagram tasks correctly on the same four layouts. Without images it answered 11 correctly.

| Run | Correct tasks | Correct pairs | Incorrect | Parse errors | Request errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| [GPT-6.2 Sol pilot vision](output/pilot/report.json) | 6/6 | 3/3 | 0 | 0 | 0 |
| [GPT-6.2 Sol held-out vision](output/heldout-vision/report.json) | 32/32 | 16/16 | 0 | 0 | 0 |
| [GPT-6.2 Sol held-out text only](output/heldout-text/report.json) | 11/32 | 3/16 | 19 | 2 | 0 |
| [GPT-6.1 Terra held-out vision](output/heldout-terra/report.json) | 28/32 | 12/16 | 4 | 0 | 0 |

| Held-out task | Sol vision | Terra vision | Sol text only |
| --- | ---: | ---: | ---: |
| Visibility | 16/16 | 12/16 | 8/16 |
| Obstruction | 8/8 | 8/8 | 1/8 |
| Repair | 8/8 | 8/8 | 2/8 |

A pair earns credit only when both replies are correct. Terra answered 2/4 mirror-angle pairs and 2/4 cosmetic control pairs correctly. Its answer changed on two control pairs where only the background color changed. All requests used Codex CLI 0.170.0, low reasoning effort and the provider’s default sampling. The individual reports store the settings, raw text, usage, duration, per-condition scores and parse decisions.

Replay surfaced three false passes across eight archived hidden visibility cases and one false reject across eight visible cases for Terra. These counts come from its saved 28/32 run on the original geometry. [Raw replies](output/heldout-terra/report.json)

## Inspect real errors

- **Outside the camera’s view** · `f639c8963cc97c61`. Terra replied `Yes.` The reflection lands inside the mirror but 4.85° outside the camera’s view. [Model input](output/heldout-vision/inputs/f639c8963cc97c61.png) · [Geometry reveal](output/heldout-vision/reveals/f639c8963cc97c61.png)
- **Beyond the mirror edge** · `186b614be1eb09a9`. Terra replied `Yes`. The candidate hit is 14.39 mm beyond the usable mirror edge. [Model input](output/heldout-vision/inputs/186b614be1eb09a9.png) · [Geometry reveal](output/heldout-vision/reveals/186b614be1eb09a9.png)

The sample covers four layout seeds. Tasks within a layout share camera and target geometry. The counts describe these runs on the generated layouts. Tabletop measurements and independent human responses are pending.
