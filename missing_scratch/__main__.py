"""Command-line entry points for the shared factory."""

import argparse
import subprocess
from pathlib import Path

from .calibration import EVIDENCE_ROOT, verified_calibration
from .factory import PILOT_SEED, generate
from .models import MODELS, evaluate
from .pack import export_pack, make_pack, write_json
from .reports import display_count, markdown, read_json, replay, verify_export


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m missing_scratch")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, description in (("generate", "Export inputs, reference answers and reveals"),
                                 ("benchmark", "Generate and score a live run or saved replies")):
        sub = commands.add_parser(command, help=description)
        sub.add_argument("--suite", choices=("pilot", "heldout", "challenge", "sandbox"), default="pilot")
        sub.add_argument("--seed", type=int, help="Seed for the sandbox suite")
        sub.add_argument("--output", type=Path, required=True, help="New output directory")
        if command == "benchmark":
            backend = sub.add_mutually_exclusive_group(required=True)
            backend.add_argument("--model", choices=MODELS)
            backend.add_argument("--replies", type=Path, help="Replay an existing report without making requests")
            sub.add_argument("--mode", choices=("vision", "text-only"), default="vision")
            sub.add_argument("--jobs", type=int, choices=range(1, 5), default=2)
            sub.add_argument("--resume", action="store_true", help="continue unfinished requests in the same output")
            sub.add_argument("--request-limit", type=int, help="maximum new requests for this invocation")
    commands.add_parser("check-calibration", help="verify the measured pilot and linked camera outcomes")
    kit = commands.add_parser("print-kit", help="Write the print-ready tabletop setup")
    kit.add_argument("--output", type=Path, required=True, help="New PDF path")
    evidence = commands.add_parser("record", help="Record an actual camera observation for a pilot task")
    evidence.add_argument("--task", required=True)
    evidence.add_argument("--stage", required=True)
    evidence.add_argument("--observer", required=True)
    evidence.add_argument("--visible", choices=("YES", "NO"), required=True)
    evidence.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "print-kit":
            from .physical import print_kit

            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as stream:
                stream.write(print_kit())
            print(args.output)
            return
        if args.command == "record":
            from .evidence import record

            tasks, _ = generate(PILOT_SEED, pilot=True)
            task = next((task for task in tasks if task.id == args.task), None)
            if task is None:
                raise ValueError("camera frame must reference a pilot task ID")
            print(record(EVIDENCE_ROOT / "captures", task, args.stage, args.observer, args.visible, args.capture))
            return
        if args.command == "check-calibration":
            print(f"Calibrated camera evidence verified · {verified_calibration()}")
            return

        live = args.command == "benchmark" and args.model is not None
        resuming = getattr(args, "resume", False)
        limit = getattr(args, "request_limit", None)
        if (resuming or limit is not None) and not live:
            raise ValueError("Resume and request limits apply only to a live benchmark")
        if limit is not None and limit < 1:
            raise ValueError("Request limit must be positive")
        calibration = verified_calibration() if live else None
        pack = make_pack(args.suite, args.seed)
        if args.suite == "sandbox" and getattr(args, "replies", None):
            document = read_json(args.replies)
            if isinstance(document, dict) and document.get("dataset_id") != pack.id:
                pack = make_pack(args.suite, args.seed, legacy_sandbox=True)
        report = replay(pack, args.replies) if getattr(args, "replies", None) else None
        if resuming:
            verify_export(pack, args.output)
            if (args.output / "report.json").exists() or (args.output / "report.json").is_symlink():
                raise ValueError("This run already has a score report")
        else:
            export_pack(pack, args.output)
            print(f"Generated {len(pack.tasks)} verified tasks from {pack.seeds} in {args.output}", flush=True)
        if args.command == "benchmark":
            if report is None:
                report = evaluate(pack, args.model, args.mode, args.jobs,
                                  lambda task_id, error: print(f"{task_id} {'request failed' if error else 'saved reply'}", flush=True),
                                  checkpoint=args.output / ".run", resume=resuming, request_limit=limit, calibration=calibration)
                missing = report["summary"]["statuses"]["missing_reply"]
                if missing:
                    print(f"Paused with {missing} tasks remaining. Resume using the same output directory.")
                    return
            write_json(args.output / "report.json", report)
            with (args.output / "report.md").open("x", encoding="utf-8") as stream:
                stream.write(markdown(report))
            overall = report["summary"]
            print(f"Accuracy {display_count(overall)}. Pair accuracy {display_count(overall, pair=True)}.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
