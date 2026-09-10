import json
from pathlib import Path
from types import SimpleNamespace

from marlow.codes import STATUS_RESOLVED
from marlow.demo import run_demo_case
from marlow.engine import start_run, ticket_status
from marlow.live import (
    build_case2_report,
    embedding_model_label,
    error_run_record,
    live_run_record,
    main as live_main,
    percentile_ms,
)
from marlow.llm import OpenAIActionProvider
from marlow.seed import L1_ID


def _stub_client(payloads: list[dict]) -> SimpleNamespace:
    remaining = list(payloads)

    def create(**kwargs):
        choice = kwargs.get("tool_choice") or {}
        fn = choice.get("function") or {}
        name = fn.get("name") or "emit_action"
        if name == "assess_evidence":
            payload = {"sufficient": True, "missing": [], "reason": "stub sufficient"}
            function = SimpleNamespace(name="assess_evidence", arguments=json.dumps(payload))
        else:
            payload = remaining.pop(0)
            function = SimpleNamespace(name="emit_action", arguments=json.dumps(payload))
        tool_call = SimpleNamespace(function=function)
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        usage = SimpleNamespace(prompt_tokens=9, completion_tokens=4)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    completions = SimpleNamespace(create=create)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _close_payloads() -> list[dict]:
    return [
        {"kind": "skill", "name": "investigate", "arguments": {"ticket_id": "INC-1001"}},
        {
            "kind": "skill",
            "name": "close_ticket",
            "arguments": {
                "ticket_id": "INC-1001",
                "kb_doc_id": "grafana-login",
                "kb_version": "10.4",
                "reason": "登录问题已按手册处理。",
            },
        },
    ]


def test_percentile_ms_n10_linear() -> None:
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert percentile_ms(values, 50) == 55.0
    assert percentile_ms(values, 95) == 95.5
    assert percentile_ms([42], 50) == 42.0
    assert percentile_ms([], 50) == 0.0


def test_embedding_model_label_hash_without_env(monkeypatch) -> None:
    monkeypatch.delenv("MARLOW_KB_EMBEDDINGS", raising=False)
    monkeypatch.delenv("MARLOW_EMBEDDING_MODEL", raising=False)
    assert embedding_model_label() == "hash-fixture"
    monkeypatch.setenv("MARLOW_KB_EMBEDDINGS", "real")
    monkeypatch.setenv("MARLOW_EMBEDDING_MODEL", "jina-embeddings-v3")
    assert embedding_model_label() == "jina-embeddings-v3"


def test_tokens_come_from_caller_held_provider_not_engine(session) -> None:
    client = _stub_client(_close_payloads())
    provider = OpenAIActionProvider(
        "请调查 INC-1001 并关单",
        client=client,
        model="gpt-4o-mini-test",
    )
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="请调查 INC-1001 并关单",
        case_id="close_success",
        provider=provider,
        real=True,
    )
    session.flush()
    assert run.outcome_code == "ok"
    assert ticket_status(session, "INC-1001") == STATUS_RESOLVED
    assert provider.prompt_tokens == 27
    assert provider.completion_tokens == 12
    assert not hasattr(run, "prompt_tokens")
    assert not hasattr(run, "completion_tokens")
    kinds = [row.kind for row in run.events]
    assert "llm" in kinds
    payloads = [json.loads(row.payload) for row in run.events if row.kind == "llm"]
    assert payloads[0]["provider"] == "openai"
    assert payloads[0]["model"] == "gpt-4o-mini-test"


def test_engine_source_has_no_api_usage_state() -> None:
    text = (Path(__file__).resolve().parents[1] / "src" / "marlow" / "engine.py").read_text(encoding="utf-8")
    assert "prompt_tokens" not in text
    assert "completion_tokens" not in text


def test_demo_report_includes_usage_latency_and_ticket(session) -> None:
    client = _stub_client(_close_payloads())
    report = run_demo_case(session, 2, real=True, llm_client=client, verbose=False)
    session.flush()
    assert report is not None
    assert report["prompt_tokens"] == 27
    assert report["completion_tokens"] == 12
    assert report["ticket_status"] == STATUS_RESOLVED
    assert report["citation"] == "grafana-login@10.4"
    assert report["latency_ms"] >= 0
    assert "p50_ms" not in report


def test_fake_demo_does_not_write_usage(session) -> None:
    report = run_demo_case(session, 2, real=False, verbose=False)
    session.flush()
    assert report is None
    assert ticket_status(session, "INC-1001") == STATUS_RESOLVED


def test_build_case2_report_aggregates_p50_tokens() -> None:
    runs = [
        {
            "latency_ms": float(v),
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "outcome_code": "ok",
            "ticket_status": "Resolved",
        }
        for v in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
    ]
    payload = build_case2_report(
        runs,
        date="2026-09-08",
        chat_model="grok-4.6",
        embedding_model="jina-embeddings-v3",
    )
    assert payload["provider"] == "openai-compat"
    assert payload["n"] == 10
    assert payload["p50_ms"] == 55.0
    assert payload["p95_ms"] == 95.5
    assert payload["prompt_tokens"] == 100
    assert payload["completion_tokens"] == 20
    assert payload["chat_model"] == "grok-4.6"
    assert payload["embedding_model"] == "jina-embeddings-v3"


def test_live_main_without_key_does_not_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("marlow.live.load_local_env", lambda: None)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = tmp_path / "report.json"
    assert live_main(["--out", str(out), "--n", "10"]) == 1
    assert not out.exists()


def test_live_run_record_redacts_and_error_record(session, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret-aaa")
    client = _stub_client(_close_payloads())
    provider = OpenAIActionProvider(
        "请调查 INC-1001 并关单",
        client=client,
        model="gpt-4o-mini-test",
    )
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="请调查 INC-1001 并关单",
        case_id="close_success",
        provider=provider,
        real=True,
    )
    session.flush()
    record = live_run_record(
        session,
        case=2,
        case_id="close_success",
        run=run,
        latency_ms=12.34,
        provider=provider,
    )
    dumped = json.dumps(record)
    assert "sk-live-secret-aaa" not in dumped
    err = error_run_record(case=2, case_id="close_success", latency_ms=1, error="sk-live-secret-aaa boom")
    assert "sk-live-secret-aaa" not in err["error"]
    assert err["prompt_tokens"] == 0
