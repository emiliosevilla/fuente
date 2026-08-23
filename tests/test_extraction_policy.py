from pathlib import Path

from fuente.extractors.policy import ExtractionPolicy


class RejectingEngine:
    def extract(self, _path: Path):
        return "\x00\x01", {}


class AcceptingEngine:
    def extract(self, _path: Path):
        return "# Título\n\nTexto legible", {}


class FailingEngine:
    def extract(self, _path: Path):
        raise ValueError("engine unavailable")


def test_policy_records_rejected_then_accepted_attempts(tmp_path):
    policy = ExtractionPolicy(engines=[RejectingEngine(), AcceptingEngine()])
    decision = policy.extract(tmp_path / "archivo.pdf")
    assert [attempt.outcome for attempt in decision.attempts] == ["rejected", "accepted"]
    assert decision.selected_engine == "accepting"
    assert decision.attempts[0].quality_score == 0.4
    assert decision.attempts[1].reasons == ()


def test_policy_distinguishes_failed_engine_from_rejected_quality(tmp_path):
    decision = ExtractionPolicy(engines=[FailingEngine()]).extract(tmp_path / "archivo.pdf")

    assert decision.attempts[0].outcome == "failed"
    assert decision.attempts[0].reasons == ("ValueError: engine unavailable",)
