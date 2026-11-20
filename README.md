# The Missing Scratch

The Missing Scratch is a Visual Task Factory for Innodata Track 2. It asks whether a camera can see a marked inspection point through a finite mirror. A model receives a scaled top-view PNG and a question. Two geometry solvers verify the reference answer before the task enters the dataset. The judge can predict first, then reveal the light path and compare it with a real model reply.

## Open the demo

Download [the browser demo](output/prototype.html) to try verified diagram pairs, reveal the ray path, and inspect archived model results. It uses pre-generated examples and runs offline. The Streamlit app below generates new tasks locally.

Use Python 3.11. From this folder, install the Python dependencies and start Streamlit.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
.venv/bin/python -m streamlit run app.py
```

Open the local judge interface. [The Missing Scratch](http://127.0.0.1:8502)

1. Start with **Flagship pair**. Predict whether the camera sees the red X, then select **Reveal answer**. Switch from **Setting 1** to **Setting 2** and predict again. The mirror rotates 18° around its center. The lens and marked part stay fixed.
2. Open **Six-task pilot** for obstruction and repair. Each obstruction has one blocking object. Each repair gives three mirror settings and one working choice.
3. Open **Fresh layout** and generate a new seed or enter a seed to reproduce a layout.
4. Open **Benchmark results** to compare archived runs. Select **GPT-6.1 Terra** to inspect a recorded vision error with the exact diagram and reply. The **Corrected challenge** tab tracks the new layout suite.
5. Download the [A4 tabletop kit](output/print/mirror-setup.pdf) to recreate both settings and all six pilot tasks. [Physical and blind validation instructions](VALIDATION.md)

### Deploy the browser demo on Vercel

Import this GitHub repository as a Vercel project from its root. `vercel.json` copies the checked-in `output/prototype.html` to `dist/index.html`. The hosted demo uses the bundled images, verified answers, printable kit, and archived model results.

Regenerate the browser export after changing the demo examples.

```sh
.venv/bin/python -m missing_scratch prototype
```

The saved replies and fresh geometry work with the local app offline. After recording the measured fixture and matching pilot frames, enable live requests with this launch command. Live evaluation uses an authenticated Codex CLI and sends generated diagrams and questions to its model provider. [Camera calibration](VALIDATION.md#recreate-the-tabletop-pilot)

```sh
MISSING_SCRATCH_LIVE=1 .venv/bin/python -m streamlit run app.py
```

## Generate and evaluate from the CLI

Generate a fresh ten-task set using a reproducible seed.

```sh
.venv/bin/python -m missing_scratch generate --suite sandbox --seed 73982 --output output/runs/new-layout
```

Generate the corrected 20-layout suite locally. When the calibration check passes, evaluate it with an authorized model. Set `--mode text-only` for the same questions without images and use a separate output directory. Supported Codex models are `gpt-6.2-sol` and `gpt-6.1-terra`.

```sh
.venv/bin/python -m missing_scratch generate --suite challenge --output output/runs/challenge-inputs
.venv/bin/python -m missing_scratch benchmark --suite challenge --model gpt-6.2-sol \
  --jobs 2 --request-limit 20 --output output/runs/challenge
```

The request limit caps new calls in this invocation. Continue with the same options plus `--resume`. A checkpoint keeps every saved response, including failures, and binds it to the exact dataset and run settings. Calls interrupted before saving may be sent again. Reports preserve false-pass, false-reject and manual-review counts for visibility tasks.

Replay the published vision run from saved raw replies without model access. Replay regenerates the inputs, verifies their image SHA-256 values, then recomputes the scores. Use a new output directory each time. The tested renderer is the pinned Python 3.11 macOS arm64 environment.

```sh
.venv/bin/python -m missing_scratch benchmark --suite heldout \
  --replies output/heldout-vision/report.json --output output/runs/replay
.venv/bin/python -m unittest discover -s tests -v
```

## What a batch contains

| Location | Contents |
| --- | --- |
| `inputs/` | Standalone PNGs and `tasks.jsonl` with task IDs, questions and image hashes |
| `reveals/` | Images with the ray path and outcome for human review |
| `answers.json` | Reference answers, full scenes, verified path checks, pair IDs and rejection counts |
| `report.json` | Run settings, raw replies, parse decisions and counts by task, pair and condition |
| `report.md` | A readable summary of the run |

The runner sends only one PNG and the question with a short answer-format instruction per vision request. The text baseline uses the exact same prompt. Each request starts in a temporary working directory, uses read-only mode, and has web, tool and plugin access disabled. Any observed tool action invalidates the reply. The CLI excludes API key variables from the subprocess environment. The Streamlit server binds to loopback with CORS and XSRF protection active.

## How the reference is verified

The primary solver reflects the target across the mirror line, then intersects the segment from the camera to that virtual image with the mirror line. It tests reflective side, usable mirror width, camera field of view and clearance on each leg. The second solver minimizes the physical path length using bisection along the mirror line, checks the view with a dot product and intersects blocker disks with the ray segments using a quadratic. Accepted cases agree on the mirror hit and every failure condition. A repair must have exactly one working angle. Removing the unique obstruction must restore the view.

Close calls are excluded within 4 mm of a mirror endpoint, 3° of the camera view edge, 2.5 mm of a blocker contact, or 6 mm of the mirror’s reflective-side boundary. The generator records why candidates were excluded. All scenes test a point, a single reflection and planar geometry. The physical check is a separate comparison against the phone camera.

The physical pilot uses seed `2026`. The four original held-out layouts (`43020`, `77499`, `16422` and `89649`) are available for archive replay. The corrected suite uses `81602` through `81621`. It varies camera aim, mirror width, added obstructions and mirror angle. Correct repair options occupy all three angle ranks, and the benchmark includes a direct-view case where the reflected view is hidden. The sandbox reserves experiment seeds and uses the corrected generator.

## Evidence and submission

- [Observed results, raw run links and example errors](RESULTS.md)
- [Validation, camera captures and blind-review procedure](VALIDATION.md)
- [Pre-release and pilot sign-offs](PRE_RELEASE.md)
- [Official hackathon brief](https://hack2skill.com/event/innodata/)
- [Official Track 2 walkthrough](https://www.youtube.com/watch?v=X6lTYulY04M&t=1151s)

The geometry, layouts, diagrams and labels are generated in this project. Streamlit supplies the interface, ReportLab supplies the vector artwork and print kit, PDFium renders the model images, Pillow prepares camera frames and Codex CLI runs the models. The Codex isolation flags follow the pattern tested in The Vanishing Barcode. The recorded answers and model replies received no manual corrections.
