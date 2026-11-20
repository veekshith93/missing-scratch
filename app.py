"""Local Streamlit judge interface for The Missing Scratch."""

import os
from pathlib import Path
from secrets import randbelow
from threading import BoundedSemaphore

import streamlit as st

from missing_scratch.calibration import verified_calibration
from missing_scratch.challenge import CHALLENGE_SEEDS
from missing_scratch.evidence import camera_result, observations
from missing_scratch.factory import HELDOUT_SEEDS, PILOT_SEED
from missing_scratch.models import MODELS, codex_completion, parse_answer, prompt_for
from missing_scratch.pack import make_pack
from missing_scratch.physical import print_kit
from missing_scratch.render import diagram, explain
from missing_scratch.reports import display_count, replay

ROOT = Path(__file__).resolve().parent
RUNS = {("pilot", "vision"): "pilot", ("heldout", "vision"): "heldout-vision",
        ("heldout", "text-only"): "heldout-text", ("heldout", "terra"): "heldout-terra",
        ("challenge", "vision"): "runs/challenge", ("challenge", "text-only"): "runs/challenge-text"}
VIEWS = ("Try a task", "Answer reveal", "Benchmark results")
SUITES = ("Flagship pair", "Six-task pilot", "Fresh layout")


@st.cache_data(max_entries=8, show_spinner=False)
def load_pack(suite, seed=None):
    return make_pack(suite, seed)


@st.cache_data(show_spinner=False)
def load_pdf():
    return print_kit()


@st.cache_data(max_entries=64, show_spinner=False)
def reveal_image(task):
    return diagram(task, reveal=True)


@st.cache_data(max_entries=8, show_spinner=False)
def load_report(suite, variant, modified):
    path = ROOT / "output" / RUNS[(suite, variant)] / "report.json"
    return replay(load_pack(suite), path)


@st.cache_resource
def model_slot():
    return BoundedSemaphore(1)


@st.cache_data(ttl=5, show_spinner=False)
def camera_verified():
    try:
        verified_calibration()
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def report_for(suite, variant="vision"):
    name = RUNS.get((suite, variant))
    if name is None:
        return None
    path = ROOT / "output" / name / "report.json"
    try:
        if path.is_file():
            return load_report(suite, variant, (path.stat().st_mtime_ns, path.stat().st_size))
    except (OSError, ValueError, RecursionError):
        st.warning("The saved report could not be verified against the current diagrams.")
    return None


def remember(key, task_id, value):
    items = st.session_state.setdefault(key, {})
    if len(items) >= 48 and task_id not in items:
        items.pop(next(iter(items)))
    items[task_id] = value


def saved(key, task_id):
    return st.session_state.get(key, {}).get(task_id)


def reveal(task_id):
    remember("revealed", task_id, True)
    st.session_state.view = VIEWS[1]


def remember_guess(task_id, widget):
    remember("guesses", task_id, st.session_state[widget])


def new_seed():
    seed = randbelow(2**32)
    while seed in (*HELDOUT_SEEDS, *CHALLENGE_SEEDS, PILOT_SEED):
        seed = randbelow(2**32)
    st.session_state.layout_seed = seed


def friendly(answer):
    if answer is None:
        return "—"
    return answer.title()


def choose_task():
    with st.sidebar:
        st.header("Scene controls")
        choice = st.radio("Task set", SUITES)
        if choice == SUITES[2]:
            st.button("Generate new layout", on_click=new_seed)
            st.session_state.setdefault("layout_seed", 73982)
            seed = st.number_input("Layout seed", min_value=0, max_value=2**32-1, step=1,
                                   key="layout_seed", help="Enter the same seed to reproduce the layout.")
            try:
                pack = load_pack("sandbox", int(seed))
            except (ValueError, RuntimeError) as error:
                st.warning(str(error))
                return None, None
        else:
            pack = load_pack("pilot")
        if choice == SUITES[0]:
            setting = st.radio("Mirror setting", ("Setting 1", "Setting 2"), horizontal=True)
            task = pack.tasks[setting == "Setting 2"]
        else:
            family = st.selectbox("Task type", ("Visibility", "Obstruction", "Repair")).lower()
            tasks = [task for task in pack.tasks if task.kind == family]
            number = st.selectbox("Example", tuple(range(1, len(tasks)+1)), format_func=lambda n: f"Example {n}")
            task = tasks[number-1]
        st.caption(f"Seed {pack.seeds[0]} · {task.id}")
        st.divider()
        st.download_button("Download tabletop setup (PDF)", load_pdf(), "mirror-setup.pdf", "application/pdf")
    return pack, task


def try_task(pack, task):
    left, right = st.columns((1.68, 1), gap="medium")
    with left:
        st.image(pack.images[task.id], width="stretch")
    with right:
        with st.container(border=True):
            st.caption(task.kind.capitalize())
            st.subheader(task.question)
            widget = f"guess_{task.id}"
            guess = saved("guesses", task.id)
            st.radio("Your prediction", task.choices, index=task.choices.index(guess) if guess in task.choices else None,
                     format_func=friendly, horizontal=True, key=widget, on_change=remember_guess, args=(task.id, widget))
            st.button("Reveal answer", type="primary", on_click=reveal, args=(task.id,))

        with st.container(border=True):
            st.markdown("#### Model prediction")
            report = report_for(pack.suite)
            if report and st.toggle("Show saved prediction", key=f"show_prediction_{task.id}"):
                reply = report["replies"].get(task.id, {})
                st.caption(f"Saved run · {report['run'].get('model', 'Model')}")
                st.text(reply.get("raw_reply") or reply.get("error") or "No reply")
            live = (os.getenv("MISSING_SCRATCH_LIVE") == "1" and st.get_option("server.address") == "127.0.0.1")
            if live and not camera_verified():
                st.caption("Camera calibration and pilot captures are required before a new model run.")
            elif live:
                previous = saved("live_replies", task.id)
                label = "Retry live prediction" if previous and previous.get("error") else "Ask vision model live"
                if st.button(label, disabled=bool(previous and not previous.get("error"))):
                    slot = model_slot()
                    if slot.acquire(blocking=False):
                        try:
                            with st.spinner("Waiting for the vision model…"):
                                reply = codex_completion(MODELS[0], prompt_for(task), pack.images[task.id])
                                remember("live_replies", task.id, reply)
                        finally:
                            slot.release()
                    else:
                        st.info("A model request is already running. Try again when it finishes.")
                reply = saved("live_replies", task.id)
                if reply:
                    st.caption(f"Live run · {MODELS[0]}")
                    st.text(reply.get("raw_reply") or reply.get("error") or "No reply")
            elif not report:
                st.caption("Live evaluation is available when the local app starts with model requests enabled.")


def answer_view(pack, task):
    if not saved("revealed", task.id):
        st.image(pack.images[task.id], width=690)
        st.button("Reveal geometry", type="primary", on_click=reveal, args=(task.id,))
        return
    left, right = st.columns((1.68, 1), gap="medium")
    with left:
        st.image(reveal_image(task), width="stretch")
    with right:
        with st.container(border=True):
            st.caption("Verified answer")
            st.subheader(friendly(task.answer))
            st.write(explain(task))
            guess = saved("guesses", task.id)
            if guess is not None:
                st.caption(f"Your prediction · {friendly(guess)} · {'Correct' if guess == task.answer else 'Incorrect'}")
            reply = saved("live_replies", task.id)
            if reply:
                parsed = parse_answer(reply.get("raw_reply"), task.choices)
                if reply.get("error"):
                    st.caption("Live model · request failed")
                else:
                    status = ("Correct" if parsed == task.answer else "Incorrect") if parsed else "Unparseable"
                    st.caption(f"Live model · {friendly(parsed)} · {status}")
            report = report_for(pack.suite)
            row = next((row for row in report["rows"] if row["id"] == task.id), None) if report else None
            if row:
                st.caption(f"Saved model · {friendly(row['parsed'])} · {row['status'].replace('_', ' ').capitalize()}")
        with st.container(border=True):
            st.markdown("#### Tabletop check")
            try:
                captures = observations(ROOT / "evidence" / "captures", task) if pack.suite == "pilot" else {}
            except (OSError, ValueError, RecursionError):
                st.warning("A saved camera observation failed verification.")
                return
            st.caption(camera_result(task, captures))
            if captures:
                for stage, (meta, frame) in captures.items():
                    st.image(frame, caption=f"{stage} · visibility {friendly(meta['observed'])}")
                    st.text(f"Observer · {meta['observer']}")


def results_view():
    suites = {"Archived held-out": "heldout", "Archived six-task pilot": "pilot", "Corrected challenge": "challenge"}
    selection = st.radio("Evaluation set", tuple(suites), horizontal=True)
    suite = suites[selection]
    if suite != "challenge":
        st.caption("Archived synthetic runs. The corrected suite has a separate calibration gate.")
    report = report_for(suite)
    if report is None:
        if suite == "challenge":
            st.info(f"{len(CHALLENGE_SEEDS)} verified layout seeds. New scores require calibrated pilot camera evidence.")
        else:
            st.info("A verified run for this set will appear here after the benchmark finishes.")
        return
    pack = load_pack(suite)
    terra = report_for(suite, "terra")
    if terra and st.radio("Model", ("GPT-6.2 Sol", "GPT-6.1 Terra"), horizontal=True) == "GPT-6.1 Terra":
        report = terra
    baseline = report_for(suite, "text-only") if report is not terra else None
    a, b, c = st.columns(3)
    a.metric("Vision accuracy", display_count(report["summary"]))
    b.metric("Vision pair accuracy", display_count(report["summary"], pair=True))
    c.metric("Text-only accuracy", display_count(baseline["summary"]) if baseline else "—")
    st.caption(f"{report['run'].get('model', 'Model')} · {len(pack.seeds)} layout seeds · Both answers must be correct for pair credit.")
    rows = []
    for kind, values in report["by_task"].items():
        row = {"Task": kind.capitalize(), "Vision": display_count(values), "Vision pairs": display_count(values, True)}
        if baseline:
            row["Text only"] = display_count(baseline["by_task"][kind])
        rows.append(row)
    st.table(rows)
    with st.expander("Visibility false passes and false rejects"):
        outcome = report["visibility_outcomes"]
        st.table([{"Outcome": "False pass", "Count": f"{outcome['false_pass']}/{outcome['hidden_cases']} hidden"},
                  {"Outcome": "False reject", "Count": f"{outcome['false_reject']}/{outcome['visible_cases']} visible"},
                  {"Outcome": "Manual review", "Count": f"{outcome['manual_review']}/{outcome['visibility_cases']} visibility"}])
    with st.expander("Pair controls and reply outcomes"):
        st.table([{"Pair changes": control.replace("-", " ").capitalize(), "Vision pairs": display_count(values, True),
                   **({"Text-only pairs": display_count(baseline["by_control"][control], True)} if baseline else {})}
                  for control, values in report["by_control"].items()])
        st.table([{"Outcome": status.replace("_", " ").capitalize(), "Vision": count,
                   **({"Text only": baseline["summary"]["statuses"][status]} if baseline else {})}
                  for status, count in report["summary"]["statuses"].items()])
    with st.expander("Results by scene condition"):
        st.table([{"Condition": condition.capitalize(), "Vision": display_count(values),
                   **({"Text only": display_count(baseline["by_condition"][condition])} if baseline else {})}
                  for condition, values in report["by_condition"].items()])

    st.subheader("Inspect a recorded reply")
    source = st.radio("Run", ("Vision", "Text only") if baseline else ("Vision",), horizontal=True)
    chosen = baseline if source == "Text only" else report
    rows = sorted(chosen["rows"], key=lambda item: item["status"] == "correct")
    labels = {row["id"]: f"{row['kind'].capitalize()} · {row['status'].replace('_', ' ')} · {row['id']}" for row in rows}
    selected = st.selectbox("Recorded example", list(labels), format_func=labels.__getitem__)
    task = next(task for task in pack.tasks if task.id == selected)
    row = next(row for row in rows if row["id"] == selected)
    a, b = st.columns((1.68, 1), gap="medium")
    with a:
        if source == "Vision":
            st.image(pack.images[task.id], width="stretch")
        else:
            st.caption("Text-only input")
            st.text(prompt_for(task))
    with b:
        with st.container(border=True):
            st.write(task.question)
            st.caption("Raw reply")
            reply = chosen["replies"].get(task.id, {})
            st.text(reply.get("raw_reply") or reply.get("error") or "No reply")
            st.caption(f"Expected {friendly(row['expected'])} · {row['status'].replace('_', ' ').capitalize()}")
            with st.expander("See the geometry"):
                st.image(reveal_image(task), width="stretch")


def main():
    st.set_page_config(page_title="The Missing Scratch", page_icon="◈", layout="wide")
    st.html("""<style>
        .stMainBlockContainer { max-width: 1230px; padding-top: 4.4rem; }
        h1 { letter-spacing: -.045em; }
        [data-testid="stImage"] img { border: 1px solid #ccdcdf; border-radius: 12px; }
        [data-testid="stMetric"] { padding: 0.8rem 1rem; background: #eaf2f3; border-radius: 10px; }
        </style>""")
    st.caption("Innodata · Visual Task Factory")
    st.title("The Missing Scratch")
    st.markdown("Predict what an inspection camera can see through a mirror.")
    st.session_state.setdefault("view", VIEWS[0])
    view = st.segmented_control("View", VIEWS, key="view", label_visibility="collapsed") or VIEWS[0]
    pack, task = choose_task()
    if view == VIEWS[2]:
        results_view()
        return
    if pack is not None:
        if view == VIEWS[0]:
            try_task(pack, task)
        else:
            answer_view(pack, task)


main()
