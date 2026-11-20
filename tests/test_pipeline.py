import io
import json
import os
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pypdfium2
from PIL import Image, ImageChops

from missing_scratch.evidence import camera_result, observations, record, stages
from missing_scratch.models import MODELS, codex_completion, codex_events, parse_answer, prompt_for, score
from missing_scratch.pack import export_pack, make_pack, write_json
from missing_scratch.physical import print_kit
from missing_scratch.render import diagram
from missing_scratch.reports import read_json, replay


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = make_pack()

    def test_report_replay_checks_hashes_and_rescores(self):
        pack = self.pack
        tasks = pack.tasks
        replies = {task.id: {"raw_reply": task.answer} for task in tasks}
        original = score(pack, replies, {"model": "fixture"})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            original["summary"]["correct"] = 3
            write_json(path, original)
            replayed = replay(make_pack(), path)
            self.assertEqual(replayed["summary"]["correct"], 6)
            original["image_sha256"][tasks[0].id] = "changed"
            path.write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, "images differ"):
                replay(pack, path)

    def test_reply_statuses_and_pair_count(self):
        tasks = self.pack.tasks
        values = {"raw_reply": "NO."}, {"raw_reply": "NO"}, {"raw_reply": "A and B"}, {"error": "timeout"}
        replies = {task.id: reply for task, reply in zip(tasks, values)}
        outcome = score(self.pack, replies, {})["summary"]
        self.assertEqual(outcome["statuses"], {"correct": 1, "incorrect": 1, "parse_error": 1,
                                               "request_error": 1, "missing_reply": 2})
        self.assertEqual(outcome["pair_correct"], 0)
        self.assertEqual(outcome["pair_total"], 3)
        with self.assertRaisesRegex(ValueError, "unknown task"):
            score(self.pack, {"../foreign": {"raw_reply": "YES"}}, {})

    def test_strict_parser(self):
        self.assertEqual(parse_answer(" yes. \n", ("YES", "NO")), "YES")
        self.assertEqual(parse_answer("b", tuple("ABC")), "B")
        for reply in ("maybe yes", "Yes, no", "YES NO", "**Yes**", "YES!", "ＹＥＳ", 1, None):
            with self.subTest(reply=reply):
                self.assertIsNone(parse_answer(reply, ("YES", "NO")))

    def test_export_keeps_reference_material_separate(self):
        with TemporaryDirectory() as folder:
            destination = Path(folder) / "batch"
            export_pack(self.pack, destination)
            manifest = (destination / "inputs" / "tasks.jsonl").read_text().splitlines()
            for line in manifest:
                entry = json.loads(line)
                self.assertEqual(set(entry), {"id", "image", "question", "sha256"})
                self.assertEqual((destination / "inputs" / entry["image"]).read_bytes(), self.pack.images[entry["id"]])
                self.assertTrue((destination / "reveals" / entry["image"]).is_file())
            self.assertEqual(len(read_json(destination / "answers.json")["tasks"]), 6)
            with self.assertRaises(FileExistsError):
                export_pack(self.pack, destination)

    def test_flagship_image_changes_only_in_mirror_region(self):
        first, second = self.pack.tasks[:2]
        a, b = (Image.open(io.BytesIO(self.pack.images[t.id])) for t in (first, second))
        x0, y0, x1, y1 = ImageChops.difference(a, b).getbbox()
        self.assertTrue(450 < x0 < x1 < 780)
        self.assertTrue(250 < y0 < y1 < 380)
        self.assertNotEqual(self.pack.images[first.id], diagram(first, reveal=True))

    def test_concurrent_diagram_renders_are_repeatable(self):
        tasks = self.pack.tasks * 8
        with ThreadPoolExecutor(max_workers=8) as pool:
            for task, png in zip(tasks, pool.map(diagram, tasks)):
                self.assertEqual(png, self.pack.images[task.id])

    def test_print_kit_matches_pack_ids_and_a4_size(self):
        with pypdfium2.PdfDocument(print_kit()) as pdf:
            self.assertEqual(len(pdf), 6)
            with closing(pdf[0]) as page:
                width, height = page.get_size()
                self.assertAlmostEqual(width * 25.4 / 72, 297, places=3)
                self.assertAlmostEqual(height * 25.4 / 72, 210, places=3)
                with closing(page.get_textpage()) as text:
                    self.assertTrue(all(t.id in text.get_text_bounded() for t in self.pack.tasks[:2]))

    def test_invalid_json_and_oversized_input(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            for value in ('{"a": 1, "a": 0}', '{"a": NaN}', '{"a": Infinity}', 'ab' * 26):
                with self.subTest(value=value):
                    path.write_text(value)
                    with self.assertRaises(ValueError):
                        read_json(path, limit=50)


class ProviderTests(unittest.TestCase):
    def test_tool_use_invalidates_reply(self):
        raw = '\n'.join(json.dumps(event) for event in (
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Yes"}},
            {"type": "item.completed", "item": {"type": "command_execution"}},
            {"type": "turn.completed"},
        ))
        self.assertEqual(codex_events(raw, 0)["tool_item_types"], ["command_execution"])
        self.assertIn("error", codex_events(raw, 0))
        for value in ('{garbled', '', '{}', '[1,2,3]'):
            self.assertIn("error", codex_events(value, 0))

    def test_model_receives_only_prompt_and_optional_png(self):
        pack = make_pack()
        task = pack.tasks[0]
        png = pack.images[task.id]
        response = '\n'.join((
            '{"type":"item.completed","item":{"type":"agent_message","text":"Yes"}}',
            '{"type":"turn.completed","usage":{"output_tokens":1}}',
        ))

        def mock_run(cmd, **options):
            files = list(Path(options["cwd"]).iterdir())
            if "--image" in cmd:
                self.assertEqual([file.name for file in files], ["input.png"])
                self.assertEqual(files[0].read_bytes(), png)
            else:
                self.assertEqual(files, [])
            self.assertIn("--ignore-user-config", cmd)
            self.assertIn("--ephemeral", cmd)
            self.assertIn("read-only", cmd)
            self.assertIn('mcp_servers={}', cmd)
            self.assertNotIn("OPENAI_API_KEY", options["env"])
            self.assertEqual(options["input"], prompt_for(task))
            self.assertNotIn(task.id, options["input"])
            self.assertNotIn(str(task.scenes[0].camera), options["input"])
            return subprocess.CompletedProcess(cmd, 0, response, "")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("missing_scratch.models.subprocess.run", side_effect=mock_run):
            for image in (png, None):
                self.assertEqual(codex_completion(MODELS[0], prompt_for(task), image)["raw_reply"], "Yes")
        with self.assertRaisesRegex(ValueError, "unsupported model"):
            codex_completion("--invalid", prompt_for(task), None)

    def test_timeout_becomes_a_request_failure(self):
        with patch("missing_scratch.models.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1)):
            reply = codex_completion(MODELS[0], "Test prompt", None)
            self.assertIn("timed out", reply["error"])


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = make_pack()

    def test_camera_status_is_manual_and_tied_to_matching_trial(self):
        task = self.pack.tasks[0]
        with TemporaryDirectory() as folder:
            root = Path(folder) / "evidence" / "captures"
            source = Path(folder) / "test-fixture.jpg"
            Image.new("RGB", (32, 24), "white").save(source, comment=b"fixture metadata")
            self.assertEqual(camera_result(task, observations(root, task)), "Awaiting physical check")
            target = record(root, task, "setup", "Test observer", "NO", source)
            results = observations(root, task)
            self.assertIn("disagree", camera_result(task, results))
            self.assertEqual(Image.open(io.BytesIO(results["setup"][1])).info, {})
            with self.assertRaisesRegex(ValueError, "already recorded"):
                record(root, task, "setup", "Test observer", "YES", source)
            with (target / "frame.png").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "integrity"):
                observations(root, task)

    def test_rejects_file_type_traversal_and_symlinks(self):
        task = self.pack.tasks[0]
        with TemporaryDirectory() as folder:
            root = Path(folder) / "captures"
            root.mkdir()
            source = Path(folder) / "not-a-photo.png"
            source.write_text("test")
            with self.assertRaisesRegex(ValueError, "invalid capture"):
                record(root, task, "setup", "Tester", "YES", source)
            with self.assertRaisesRegex(ValueError, "invalid trial"):
                record(root, task, "../escape", "Tester", "YES", source)
            (root / task.id).symlink_to(Path(folder), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "regular project files"):
                record(root, task, "setup", "Tester", "YES", source)

    def test_obstruction_and_repair_require_every_trial(self):
        for task in (self.pack.tasks[2], self.pack.tasks[4]):
            answers = {stage: ({"observed": "YES" if stage in (task.answer, f"remove-{task.answer}") else "NO"}, b"")
                       for stage in stages(task)}
            self.assertIn("agree with", camera_result(task, answers))
            answers.pop(next(iter(answers)))
            self.assertIn("trials recorded", camera_result(task, answers))
