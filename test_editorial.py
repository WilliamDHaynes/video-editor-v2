"""Zero-network editorial and accounting tests; synthetic dialogue only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import editorial as ed
import analyze_openai as ai
import budget


def payload(kind="candidates"):
    fixture = ed.fixture_report(kind)
    return {k: copy.deepcopy(fixture[k]) for k in ("verdict", "rationale", "uncertainty", "candidates")}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.report = ed.fixture_report("candidates")

    def test_reject_all_and_uncertain_are_valid_empty_results(self):
        for kind in ("reject_all", "uncertain"):
            result = ed.validate_judgment(payload(kind), self.report, "coarse")
            self.assertEqual(result["candidates"], [])

    def test_candidate_verdict_requires_a_candidate(self):
        value = payload(); value["candidates"] = []
        with self.assertRaises(ValueError): ed.validate_judgment(value, self.report, "coarse")

    def test_invented_quote_unknown_frame_and_loudness_rejected(self):
        for evidence in ([{"kind": "transcript", "ref": "t01", "quote": "I won the battle"}],
                         [{"kind": "frame", "ref": "missing", "observation": "A ship"}],
                         [{"kind": "loudness", "ref": "peak"}], [None]):
            value = payload(); value["candidates"][0]["evidence"] = evidence
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                ed.validate_judgment(value, self.report, "coarse")

    def test_invalid_boundaries_and_missing_uncertainty_rejected(self):
        for start, end in [(float("nan"), 40), (True, 40), (12, 100), (40, 12), (12, 14)]:
            value = payload(); value["candidates"][0].update(start=start, end=end)
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                ed.validate_judgment(value, self.report, "coarse")
        value = payload(); value["uncertainty"] = []
        with self.assertRaises(ValueError): ed.validate_judgment(value, self.report, "coarse")

    def test_overlapping_candidates_rejected(self):
        value = payload(); value["candidates"].append(copy.deepcopy(value["candidates"][0]))
        with self.assertRaises(ValueError): ed.validate_judgment(value, self.report, "coarse")

    def test_dense_cannot_move_to_uninspected_region(self):
        with self.assertRaises(ValueError):
            ed.validate_judgment(payload(), self.report, "dense", [(50, 90)])
        final = ed.validate_judgment(payload(), self.report, "dense", [(10, 50)])
        self.assertEqual(final["candidates"][0]["context"], {"start": 10, "end": 50})

    def test_dense_sampling_is_bounded_with_context(self):
        candidates = [{"context": {"start": a, "end": a+80}} for a in (120, 240, 360)]
        times = ed.dense_plan(candidates)
        self.assertLessEqual(len(times), 96)
        self.assertEqual(times[0], 120)
        self.assertEqual(times, sorted(set(times)))
        self.assertTrue(all(any(c["context"]["start"] <= t < c["context"]["end"] for c in candidates) for t in times))
        self.assertTrue(any(t > 438 for t in times))

    def test_coarse_reject_all_never_samples_dense(self):
        gateway, dense, persist = Mock(), Mock(), Mock()
        gateway.judge.return_value = payload("reject_all")
        ed.selection_pipeline(self.report, gateway, dense, persist, Mock())
        dense.assert_not_called(); self.assertEqual(gateway.judge.call_count, 1)
        self.assertEqual(self.report["status"], "complete")

    def test_dense_can_reject_all_prior_candidates(self):
        gateway, dense = Mock(), Mock(return_value=[])
        gateway.judge.side_effect = [payload(), payload("reject_all")]
        ed.selection_pipeline(self.report, gateway, dense, Mock(), Mock())
        dense.assert_called_once(); self.assertEqual(gateway.judge.call_count, 2)
        self.assertEqual(self.report["candidates"], [])
        self.assertEqual([s["verdict"] for s in self.report["stages"]], ["candidates", "reject_all"])

    def test_fixture_cannot_be_reviewed_or_exported(self):
        with self.assertRaises(ValueError): ed.set_review(self.report, "c01", "keep", 12, 48, "", True)
        with self.assertRaises(ValueError): ed.reviewed_ranges(self.report)

    def test_real_keep_requires_completed_source_review(self):
        # A synthetic test object is marked real only in memory to exercise the gate.
        self.report["mode"] = "real"
        with self.assertRaises(ValueError): ed.set_review(self.report, "c01", "keep", 12, 48, "", False)
        with self.assertRaises(ValueError): ed.set_review(self.report, "c01", "keep", 0, 90, "", True)
        ed.set_review(self.report, "c01", "keep", 12, 48, "Test review", True)
        self.assertEqual(len(ed.reviewed_ranges(self.report)), 1)
        ed.set_review(self.report, "c01", "reject", 12, 48, "Weak payoff", True)
        self.assertEqual(ed.reviewed_ranges(self.report), [])
        self.report["status"] = "blocked"
        with self.assertRaises(ValueError): ed.set_review(self.report, "c01", "keep", 12, 48, "", True)

    def test_empty_real_timeline_is_not_fabricated(self):
        report = ed.empty_report()
        self.assertEqual(len(report["transcript"]), 12)
        self.assertTrue(all(t["text"] is None for t in report["transcript"]))
        self.assertEqual(report["candidates"], [])
        self.assertEqual(len(report["frames"]), 12)
        self.assertTrue(all(f["path"].startswith("sample-frames/") for f in report["frames"]))

    def test_missing_key_never_constructs_client_or_reserves(self):
        with patch.object(ai, "OpenAIGateway") as gateway, patch.object(budget, "reserve") as reserve:
            with self.assertRaises(RuntimeError): ai.analyze("", 0, Mock())
            gateway.assert_not_called(); reserve.assert_not_called()


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="editorial-test-", dir=ed.ROOT)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(budget, "ROOT", self.root), patch.object(budget, "LEDGER", self.root/"ledger.json"), patch.object(ai, "ROOT", self.root)]
        from PIL import Image
        (self.root/"sample-frames").mkdir()
        for second in range(120,480,30):
            Image.new("RGB", (640,360), (30,40,50)).save(self.root/"sample-frames"/f"source_{second:04d}s.jpg")
        for p in self.patches: p.start()
        self.gateway = ai.OpenAIGateway.__new__(ai.OpenAIGateway)
        self.gateway.run_dir = self.root
        self.gateway.client = Mock()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        assert self.root.resolve().parent == ed.ROOT.resolve()
        self.temp.cleanup()

    def test_paid_vision_is_reserved_before_dispatch_and_metered(self):
        def response(**kwargs):
            ledger = budget.summary()
            self.assertEqual(ledger["uncertain_requests"], 1)
            self.assertEqual(kwargs["store"], False)
            self.assertEqual(kwargs["max_output_tokens"], 4000)
            self.assertEqual(kwargs["text"]["format"]["type"], "json_schema")
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=4000, output_tokens=200),
                                   output_text=json.dumps(payload("reject_all")), status="completed")
        self.gateway.client.responses.create.side_effect = response
        result = self.gateway.judge(ed.empty_report(), "coarse")
        self.assertEqual(result["verdict"], "reject_all")
        self.assertEqual(budget.summary()["requests"][0]["status"], "completed_metered")
        self.assertEqual(budget.summary()["counted_usd"], "0.003900")

    def test_uncertain_request_is_reserved_and_not_retried(self):
        self.gateway.client.responses.create.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError): self.gateway.judge(ed.empty_report(), "coarse")
        row = budget.summary()["requests"][0]
        self.assertEqual(row["status"], "uncertain")
        self.assertEqual(row["reserved_usd"], row["counted_usd"])
        with self.assertRaises(RuntimeError): self.gateway.judge(ed.empty_report(), "coarse")
        self.assertEqual(self.gateway.client.responses.create.call_count, 1)

    def test_known_paid_but_invalid_response_does_not_retry(self):
        self.gateway.client.responses.create.return_value = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=4000, output_tokens=50), output_text="{broken", status="incomplete")
        with self.assertRaises(RuntimeError): self.gateway.judge(ed.empty_report(), "coarse")
        self.assertTrue((self.root/"coarse-response.json").exists())
        self.assertEqual(budget.summary()["requests"][0]["status"], "completed_metered")
        self.assertEqual(self.gateway.client.responses.create.call_count, 1)

    def test_transcription_retains_conservative_bound(self):
        path = self.root/"fixture-audio.mp3"; path.write_bytes(b"mock content; never uploaded")
        self.gateway.client.audio.transcriptions.create.return_value = SimpleNamespace(text="Synthetic test speech")
        text = self.gateway.transcribe(path, {"start": 120}, 0)
        self.assertEqual(text, "Synthetic test speech")
        row = budget.summary()["requests"][0]
        self.assertEqual(row["status"], "completed_upper_bound_retained")
        self.assertEqual(row["counted_usd"], "0.010000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
