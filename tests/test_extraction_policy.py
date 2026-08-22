from pathlib import Path

from fuente.extractors.policy import ExtractionPolicy


class RejectingEngine:
    def extract(self, _path: Path):
        return "\x00\x01", {}


class AcceptingEngine:
    def extract(self, _path: Path):
        return "# Título\n\nTexto legible", {}


def test_policy_records_rejected_then_accepted_attempts(tmp_path):
    policy = ExtractionPolicy(engines=[RejectingEngine(), AcceptingEngine()])
    decision = policy.extract(tmp_path / "archivo.pdf")
    assert [attempt.outcome for attempt in decision.attempts] == ["rejected", "accepted"]
    assert decision.selected_engine == "accepting"
