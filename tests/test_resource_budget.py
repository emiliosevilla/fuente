"""Task 5.1 — resource budgets and honest memory measurement."""

from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from fuente.ram_governor.budget import (
    MODEL_CATALOG,
    BudgetDecision,
    OLLAMA_PURGE_KEEP_ALIVE,
    MeasurementStatus,
    ResourceKind,
    evaluate_resource,
    list_resource_budgets,
    measured_snapshot,
    select_optimal_model,
    select_llm_model,
    unavailable_snapshot,
)
from fuente.ram_governor.governor import RAMGovernor


class TestResourceBudgets(unittest.TestCase):
    def test_all_workload_budgets_defined(self):
        kinds = {b["kind"] for b in list_resource_budgets()}
        self.assertEqual(
            kinds,
            {
                "text_extraction",
                "ocr",
                "audio_transcription",
                "embeddings",
                "llm_inference",
            },
        )

    def test_model_metadata_includes_ram_context_concurrency(self):
        for entry in MODEL_CATALOG:
            self.assertGreater(entry.estimated_ram_gb, 0)
            self.assertGreater(entry.context_size, 0)
            self.assertGreaterEqual(entry.concurrency_limit, 1)

    def test_candidate_model_is_selected_from_ram_without_a_benchmark(self):
        candidate = next(item for item in MODEL_CATALOG if item.id == "qwen3.5:0.8b")
        self.assertEqual(candidate.context_size, 4096)
        self.assertEqual(candidate.concurrency_limit, 1)
        snap = measured_snapshot(total_gb=6.0, available_gb=3.5, safety_margin_pct=0.35)
        decision = select_optimal_model(snap)
        self.assertEqual(decision.model_id, "qwen3.5:0.8b")

    def test_unavailable_snapshot_never_invents_available_gb(self):
        snap = unavailable_snapshot(0.35, error="test", total_gb=16.0)
        self.assertIs(snap.status, MeasurementStatus.MEASUREMENT_UNAVAILABLE)
        self.assertIsNone(snap.available_gb)
        self.assertIsNone(snap.used_pct)
        self.assertEqual(snap.total_gb, 16.0)

    def test_select_llm_when_unmeasured_is_conservative_with_reason(self):
        decision = select_llm_model(unavailable_snapshot(0.35, error="no_psutil"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.model_id, "qwen2.5:1.5b")
        self.assertIn("measurement_unavailable", decision.reason)
        self.assertIsNone(decision.available_gb)

    def test_select_llm_when_measured_has_budget_decision_and_reason(self):
        snap = measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
        decision = select_llm_model(snap)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.model_id, "qwen2.5:7b")
        self.assertIn("qwen2.5:7b", decision.reason)
        self.assertIsNotNone(decision.estimated_ram_gb)
        self.assertEqual(decision.measurement_status, MeasurementStatus.MEASURED)

    def test_heavy_resource_refused_when_unmeasured(self):
        snap = unavailable_snapshot(0.35)
        for kind in (
            ResourceKind.OCR,
            ResourceKind.AUDIO_TRANSCRIPTION,
            ResourceKind.EMBEDDINGS,
            ResourceKind.LLM_INFERENCE,
        ):
            decision = evaluate_resource(kind, snap)
            self.assertFalse(decision.allowed, kind)
            self.assertIn("measurement_unavailable", decision.reason)

    def test_text_extraction_allowed_conservatively_when_unmeasured(self):
        decision = evaluate_resource(
            ResourceKind.TEXT_EXTRACTION, unavailable_snapshot(0.35)
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.concurrency_limit, 1)

    def test_select_llm_prefers_sub_2gb_model_on_4gb_host(self):
        snap = measured_snapshot(
            total_gb=4.0, available_gb=2.2, safety_margin_pct=0.35
        )
        decision = select_llm_model(snap)
        self.assertIn(
            decision.model_id, {"qwen2.5:0.5b", "qwen2.5:1.5b"}
        )
        self.assertTrue(
            (decision.estimated_ram_gb or 0) <= 2.0 or not decision.allowed
        )

    def test_select_llm_denies_when_nothing_fits_tiny_host(self):
        snap = measured_snapshot(
            total_gb=3.0, available_gb=0.8, safety_margin_pct=0.35
        )
        decision = select_llm_model(snap)
        self.assertTrue(
            decision.model_id == "qwen2.5:0.5b" or not decision.allowed
        )
        if not decision.allowed:
            self.assertIn("bm25_only", decision.reason.lower())
            self.assertIsNone(decision.model_id)


class TestRAMGovernorBudgets(unittest.TestCase):
    def test_setup_optimal_model_skips_ollama_for_bm25_only(self):
        gov = RAMGovernor()
        decision = BudgetDecision(
            allowed=False,
            resource_kind=ResourceKind.LLM_INFERENCE,
            reason="bm25_only; no catalog model fits usable_headroom_gb=0.52",
            model_id=None,
        )
        ram_info = {
            "measurement_status": "measured",
            "total_gb": 3.0,
            "available_gb": 0.8,
        }
        output = StringIO()

        with mock.patch.object(gov, "get_system_ram_info", return_value=ram_info):
            with mock.patch.object(gov, "recommend_model_decision", return_value=decision):
                with mock.patch.object(gov, "check_ollama_status") as check_status:
                    with mock.patch.object(gov, "ensure_model_available") as ensure_model:
                        with redirect_stdout(output):
                            result = gov.setup_optimal_model()

        self.assertEqual(result, "")
        self.assertIn("BM25-only", output.getvalue())
        check_status.assert_not_called()
        ensure_model.assert_not_called()

    def test_macos_fallback_does_not_fabricate_available_gb(self):
        gov = RAMGovernor(safety_margin_pct=0.35)
        with mock.patch("fuente.ram_governor.governor.HAS_PSUTIL", False):
            with mock.patch("sys.platform", "darwin"):
                with mock.patch("subprocess.check_output", return_value=b"17179869184"):
                    info = gov.get_system_ram_info()
        self.assertEqual(info["measurement_status"], "measurement_unavailable")
        self.assertIsNone(info["available_gb"])
        self.assertEqual(info["total_gb"], 16.0)
        self.assertNotIsInstance(info["available_gb"], float)

    def test_psutil_path_reports_measured_values(self):
        gov = RAMGovernor(safety_margin_pct=0.35)
        mock_mem = mock.MagicMock()
        mock_mem.total = 32 * (1024**3)
        mock_mem.available = 20 * (1024**3)
        mock_psutil = mock.MagicMock()
        mock_psutil.virtual_memory.return_value = mock_mem

        with mock.patch("fuente.ram_governor.governor.HAS_PSUTIL", True):
            with mock.patch("fuente.ram_governor.governor.psutil", mock_psutil):
                info = gov.get_system_ram_info()
                decision = gov.recommend_model_decision()

        self.assertEqual(info["measurement_status"], "measured")
        self.assertAlmostEqual(info["available_gb"], 20.0, places=1)
        self.assertEqual(decision.model_id, "qwen2.5:7b")
        self.assertTrue(decision.reason)
        self.assertEqual(gov.last_budget_decision()["model_id"], "qwen2.5:7b")

    def test_recommend_model_always_stores_decision_reason(self):
        gov = RAMGovernor()
        with mock.patch.object(
            gov,
            "measure_memory",
            return_value=unavailable_snapshot(0.35, error="forced"),
        ):
            model = gov.recommend_model()
            decision = gov.last_budget_decision()
        self.assertEqual(model, "qwen2.5:1.5b")
        self.assertIsNotNone(decision)
        self.assertIn("measurement_unavailable", decision["reason"])

    def test_get_ollama_process_state_records_failure_without_crash(self):
        gov = RAMGovernor(ollama_url="http://127.0.0.1:9")
        with mock.patch.object(
            gov, "_http_json", side_effect=RuntimeError("connection refused")
        ):
            state = gov.get_ollama_process_state()
        self.assertFalse(state["ok"])
        self.assertEqual(state["models"], [])
        self.assertIn("ollama_ps_failed", state["error"])
        self.assertIsNotNone(gov._last_ollama_state_error)

    def test_get_ollama_process_state_success(self):
        gov = RAMGovernor()
        payload = {"models": [{"name": "qwen2.5:7b", "size": 1}]}
        with mock.patch.object(gov, "_http_json", return_value=payload):
            state = gov.get_ollama_process_state()
        self.assertTrue(state["ok"])
        self.assertEqual(len(state["models"]), 1)
        self.assertIsNone(state["error"])

    def test_cycle_waits_with_instruction_when_downloaded_model_no_longer_fits(self):
        gov = RAMGovernor()
        constrained = measured_snapshot(
            total_gb=32.0, available_gb=4.0, safety_margin_pct=0.35
        )
        with mock.patch.object(
            gov, "measure_memory", side_effect=[constrained, constrained]
        ):
            with mock.patch.object(
                gov,
                "_http_json",
                return_value={
                    "models": [
                        {"name": "qwen2.5:7b"},
                        {"name": "qwen2.5:1.5b"},
                    ]
                },
            ):
                waiting = gov.check_cycle_model("qwen2.5:7b")

        self.assertFalse(waiting["allowed"])
        self.assertTrue(waiting["requires_user_confirmation"])
        self.assertEqual(waiting["compatible_model"], "qwen2.5:1.5b")
        self.assertIn("Cierra aplicaciones", waiting["instruction"])
        self.assertIn("confirm", waiting["instruction"].lower())

    def test_cycle_authorization_can_use_installed_compatible_model(self):
        gov = RAMGovernor()
        constrained = measured_snapshot(
            total_gb=32.0, available_gb=4.0, safety_margin_pct=0.35
        )
        with mock.patch.object(
            gov, "measure_memory", side_effect=[constrained, constrained]
        ):
            with mock.patch.object(
                gov,
                "_http_json",
                return_value={
                    "models": [
                        {"name": "qwen2.5:7b"},
                        {"name": "qwen2.5:1.5b"},
                    ]
                },
            ):
                resumed = gov.check_cycle_model(
                    "qwen2.5:7b", authorize_model_load=True
                )

        self.assertTrue(resumed["allowed"])
        self.assertTrue(resumed["authorization_used"])
        self.assertEqual(resumed["model_id"], "qwen2.5:1.5b")

    def test_cycle_reports_no_compatible_model_without_confirmation(self):
        gov = RAMGovernor()
        tiny = measured_snapshot(
            total_gb=3.0, available_gb=0.8, safety_margin_pct=0.35
        )
        with mock.patch.object(gov, "measure_memory", return_value=tiny):
            with mock.patch.object(
                gov,
                "_http_json",
                return_value={"models": [{"name": "qwen2.5:7b"}]},
            ):
                waiting = gov.check_cycle_model("qwen2.5:7b")

        self.assertFalse(waiting["allowed"])
        self.assertEqual(waiting["reason"].split(";", 1)[0], "no_compatible_model")
        self.assertFalse(waiting["requires_user_confirmation"])
        self.assertEqual(waiting["compatible_model"], None)

    def test_purge_model_uses_keep_alive_zero_not_force_kill(self):
        gov = RAMGovernor()
        captured = {}

        def fake_http(method, path, payload=None, timeout=5.0):
            captured["method"] = method
            captured["path"] = path
            captured["payload"] = payload
            return {"done": True, "done_reason": "unload"}

        with mock.patch.object(gov, "_http_json", side_effect=fake_http):
            result = gov.purge_model("qwen2.5:7b")

        self.assertTrue(result["ok"])
        self.assertFalse(result["force_kill"])
        self.assertEqual(result["policy"], "keep_alive=0")
        self.assertEqual(captured["path"], "/api/generate")
        self.assertEqual(captured["payload"]["keep_alive"], OLLAMA_PURGE_KEEP_ALIVE)
        self.assertEqual(captured["payload"]["keep_alive"], 0)
        self.assertEqual(captured["payload"]["prompt"], "")

    def test_purge_model_failure_is_recorded(self):
        gov = RAMGovernor()
        with mock.patch.object(gov, "_http_json", side_effect=TimeoutError("slow")):
            result = gov.purge_model("qwen2.5:1.5b")
        self.assertFalse(result["ok"])
        self.assertFalse(result["force_kill"])
        self.assertIn("purge_failed", result["error"])

    def test_evaluate_resource_budget_via_governor(self):
        gov = RAMGovernor()
        with mock.patch.object(
            gov,
            "measure_memory",
            return_value=measured_snapshot(
                total_gb=16.0, available_gb=8.0, safety_margin_pct=0.35
            ),
        ):
            decision = gov.evaluate_resource_budget("text_extraction")
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["resource_kind"], "text_extraction")
        self.assertIn("estimated_ram_gb", decision["reason"])


if __name__ == "__main__":
    unittest.main()
