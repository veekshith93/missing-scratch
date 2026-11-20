from dataclasses import replace
from random import Random
import unittest

from missing_scratch.factory import HELDOUT_SEEDS, PILOT_SEED, generate, make_task, pilot_base
from missing_scratch.geometry import Blocker, LEGS, add, direction, fermat, mul, trace, verified_trace
from missing_scratch.pack import validate_pairs


class ReflectionTests(unittest.TestCase):
    def setUp(self):
        self.base = pilot_base()

    def test_analytic_horizontal_mirror(self):
        check = verified_trace(self.base)
        self.assertTrue(check.visible)
        self.assertAlmostEqual(check.hit[0], 52 + (216 - 52) * 77 / (77 + 71))
        self.assertAlmostEqual(check.hit[1], 106)
        self.assertEqual(fermat(self.base)[1:], ((), ()))

    def test_miss_and_outside_view_are_separate_failures(self):
        miss = verified_trace(replace(self.base, angle=18))
        outside = verified_trace(replace(self.base, yaw=self.base.yaw + 45))
        self.assertEqual(miss.reasons, ("mirror edge miss",))
        self.assertLess(miss.mirror_mm, -15)
        self.assertGreater(miss.fov_deg, 0)
        self.assertEqual(outside.reasons, ("outside field of view",))
        self.assertGreater(outside.mirror_mm, 0)

    def test_reflective_backside(self):
        check = verified_trace(replace(self.base, angle=180))
        self.assertEqual(check.reasons, ("mirror backside",))
        self.assertIsNone(check.hit)

    def test_mirror_endpoint_is_rejected(self):
        x, y = trace(self.base).hit
        with self.assertRaisesRegex(ValueError, "mirror edge margin"):
            verified_trace(replace(self.base, mirror=(x + self.base.length/2, y)))

    def test_fov_edge_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "field of view margin"):
            verified_trace(replace(self.base, yaw=self.base.yaw + self.base.half_fov))

    def test_near_backside_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "reflective side margin"):
            verified_trace(replace(self.base, target=(self.base.target[0], self.base.mirror[1]-1)))

    def test_obstacle_tangency_is_rejected(self):
        hit = trace(self.base).hit
        midpoint = mul(add(hit, self.base.camera), 0.5)
        dx, dy = direction(self.base.yaw)
        center = add(midpoint, mul((-dy, dx), 9))
        with self.assertRaisesRegex(ValueError, "blocker clearance margin"):
            verified_trace(replace(self.base, blockers=(Blocker("A", center, 9),)))

    def test_bad_scene_geometry_is_rejected(self):
        for scene in (replace(self.base, length=float("nan")), replace(self.base, length=500),
                      replace(self.base, camera=self.base.target),
                      replace(self.base, blockers=(Blocker("A", self.base.camera, 7),)),
                      replace(self.base, blockers=(Blocker("A", (80, 35), 7), Blocker("B", (82, 35), 7)))):
            with self.subTest(scene=scene), self.assertRaises(ValueError):
                verified_trace(scene)

    def test_small_fixture_errors_preserve_pilot_answers(self):
        rng = Random(12)
        pilot, _ = generate(PILOT_SEED, pilot=True)

        def jitter(point):
            return add(point, (rng.uniform(-1, 1), rng.uniform(-1, 1)))

        for task in pilot:
            for scene, expected in zip(task.scenes, task.checks):
                for _ in range(120):
                    noisy = replace(scene, camera=jitter(scene.camera), target=jitter(scene.target),
                                    mirror=jitter(scene.mirror), yaw=scene.yaw + rng.uniform(-1, 1),
                                    angle=scene.angle + rng.uniform(-1, 1),
                                    blockers=tuple(replace(b, center=jitter(b.center)) for b in scene.blockers))
                    actual = trace(noisy)
                    self.assertEqual((actual.visible, actual.blocked), (expected.visible, expected.blocked))


class FactoryTests(unittest.TestCase):
    def test_six_pilot_tasks(self):
        tasks, rejected = generate(PILOT_SEED, pilot=True)
        self.assertEqual([t.kind for t in tasks], ["visibility"]*2 + ["obstruction"]*2 + ["repair"]*2)
        self.assertEqual(tuple(t.answer for t in tasks[:2]), ("YES", "NO"))
        self.assertEqual(tasks[0].question, tasks[1].question)
        self.assertTrue(rejected)
        validate_pairs(tasks)

    def test_each_obstruction_is_causal(self):
        tasks, _ = generate(PILOT_SEED, pilot=True)
        for task, leg in zip(tasks[2:4], LEGS):
            scene = task.scenes[0]
            self.assertEqual(verified_trace(scene).blocked, ((task.answer, leg),))
            for label in "ABC":
                remaining = tuple(b for b in scene.blockers if b.label != label)
                self.assertEqual(verified_trace(replace(scene, blockers=remaining)).visible, label == task.answer)

    def test_repair_constraints(self):
        tasks, _ = generate(PILOT_SEED, pilot=True)
        task = tasks[4]
        working = next(s for s, check in zip(task.scenes, task.checks) if check.visible)
        failed = next(s for s, check in zip(task.scenes, task.checks) if not check.visible)
        self.assertEqual(sum(c.visible for c in task.checks), 1)
        wrong_layout = replace(failed, target=add(failed.target, (3, 0)))
        with self.assertRaises(ValueError):
            make_task(task.layout, "repair-options", "repair", task.condition, (working, failed, wrong_layout))
        with self.assertRaises(ValueError):
            make_task(task.layout, "repair-options", "repair", task.condition, (working, working, failed))

    def test_large_seed_sweep(self):
        for seed in (*range(512), 2**32-1):
            with self.subTest(seed=seed):
                tasks, _ = generate(seed)
                self.assertEqual(len(tasks), 8)
                validate_pairs(tasks)

    def test_split_directions_and_cosmetic_colors(self):
        pilot, _ = generate(PILOT_SEED, pilot=True)
        layouts, directions, causes, colors = {pilot[0].layout}, set(), set(), set()
        for seed in HELDOUT_SEEDS:
            batch, _ = generate(seed)
            self.assertNotIn(batch[0].layout, layouts)
            layouts.add(batch[0].layout)
            yes, no = sorted(batch[:2], key=lambda task: task.answer == "NO")
            directions.add(no.scenes[0].angle > yes.scenes[0].angle)
            causes.add(no.condition)
            self.assertNotEqual(batch[-1].tinted, batch[-2].tinted)
            self.assertEqual(batch[-1].answer, batch[-2].answer)
            self.assertEqual(batch[-1].scenes, batch[-2].scenes)
            colors.add(batch[-1].answer)
        self.assertEqual(directions, {True, False})
        self.assertEqual(causes, {"mirror edge miss", "outside field of view"})
        self.assertEqual(colors, {"YES", "NO"})

    def test_invalid_seed_is_rejected(self):
        for seed in (-1, 2**32, 1.2, True, "2026"):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                generate(seed)
