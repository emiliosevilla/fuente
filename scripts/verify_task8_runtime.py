#!/usr/bin/env python3
"""Task 8 runtime proof: zero-document AnythingLLM chat with session history."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fuente.integrations.anythingllm import AnythingLLMConversationClient
from fuente.ram_governor.governor import RAMGovernor

DEFAULT_BASE_URL = "http://127.0.0.1:13001"
DEFAULT_API_KEY = "PRE0W9G-ZYQ41XZ-QM56MH9-QYSEKVG"
DEFAULT_WORKSPACE = "fuente"
DEFAULT_MODEL = "qwen2.5:0.5b"
SESSION_ID = "fuente-task8-runtime"
EVIDENCE_PATH = REPO / "docs" / "evidence" / "fuente-y-caudal" / "anythingllm-runtime.json"


def main() -> int:
    base_url = os.environ.get("FUENTE_ANYTHINGLLM_URL", DEFAULT_BASE_URL).strip()
    api_key = os.environ.get("FUENTE_ANYTHINGLLM_API_KEY", DEFAULT_API_KEY).strip()
    workspace = os.environ.get("FUENTE_ANYTHINGLLM_WORKSPACE", DEFAULT_WORKSPACE).strip()
    model = os.environ.get("FUENTE_ANYTHINGLLM_MODEL", DEFAULT_MODEL).strip()

    client = AnythingLLMConversationClient(
        base_url,
        workspace,
        api_key=api_key,
    )
    governor = RAMGovernor()
    readiness = governor.ensure_anythingllm_chat_ready(client, model)
    health = client.health()
    document_count = client.document_count()

    first = client.chat(
        session_id=SESSION_ID,
        prompt="Recuerda el token PLASMA-77 para esta sesión.",
        model=model,
    )
    second = client.chat(
        session_id=SESSION_ID,
        prompt="¿Qué token te pedí recordar en esta sesión?",
        model=model,
    )
    first_text = str(first.get("textResponse") or "")
    second_text = str(second.get("textResponse") or "")
    history_recovered = "PLASMA-77" in second_text.upper()

    try:
        git_head = (
            subprocess.check_output(
                ["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
                cwd=REPO,
                text=True,
            )
            .strip()
        )
    except (OSError, subprocess.CalledProcessError):
        git_head = ""

    report = {
        "task": 8,
        "git_head": git_head,
        "base_url": base_url,
        "workspace": workspace,
        "session_id": SESSION_ID,
        "model": model,
        "document_count": document_count,
        "health_ok": bool(health.get("ok")),
        "readiness": readiness,
        "first_chat_id": first.get("chatId"),
        "second_chat_id": second.get("chatId"),
        "first_response": first_text,
        "second_response": second_text,
        "history_recovered": history_recovered,
        "g6_status": "PASS" if document_count == 0 and history_recovered else "FAIL",
        "complete": True,
    }

    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))

    ok = (
        report["complete"]
        and document_count == 0
        and history_recovered
        and bool(readiness.get("ok"))
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
