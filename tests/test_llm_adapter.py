"""WP1: LLM adapter — fake-provider tests (retry, repair, quota cooldown, cache key, schema reject)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from llm import client
from llm.config import ConfigError, load_config, stage_settings
from llm.providers.claude_cli import ClaudeCLI, classify, parse_reset
from llm.types import LLMSchemaError, LLMUnavailable, RawRequest, RawResponse

FIX = Path(__file__).parent / "fixtures" / "llm"
PLATE_OK = {"plates": [{"n": 1, "shows": "x", "fail": None}]}


class Fake:
    """Scripted provider: returns queued RawResponses, records the requests."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls = []

    def complete(self, req):
        self.calls.append(req)
        return self.queue.pop(0)


def ok(data=None, text=None):
    return RawResponse(text=text if text is not None else json.dumps(data), data=data,
                       usage={"cost_usd": 0.01})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BUILD_DIR", str(tmp_path))
    client.reset()
    sleeps = []
    monkeypatch.setattr(client, "_sleep", sleeps.append)
    cfg = load_config()
    cfg["providers"]["gemini"]["enabled"] = True   # let chains reach a second fake provider
    monkeypatch.setattr(client, "_cfg", cfg)

    def install(**fakes):
        for name, f in fakes.items():
            client._providers[name] = f
    yield install, sleeps, tmp_path
    client.reset()


def ledger(tmp_path):
    p = tmp_path / "llm_ledger.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_success_writes_ledger_and_cache(env):
    install, _, tmp = env
    f = Fake(ok(PLATE_OK))
    install(claude_cli=f)
    r1 = client.ask("plate_qa", "check", schema="plate_qa")
    assert r1.data == PLATE_OK and not r1.cached and r1.provider == "claude_cli" and r1.model == "sonnet"
    r2 = client.ask("plate_qa", "check", schema="plate_qa")
    assert r2.cached and r2.data == PLATE_OK and len(f.calls) == 1
    rows = ledger(tmp)
    assert [r["cached"] for r in rows] == [False, True] and rows[0]["stage"] == "plate_qa"
    assert "prompt" not in rows[0]


def test_cache_disabled_calls_again(env):
    install, _, _ = env
    f = Fake(ok(PLATE_OK), ok(PLATE_OK))
    install(claude_cli=f)
    client.ask("plate_qa", "p", schema="plate_qa", cache=False)
    client.ask("plate_qa", "p", schema="plate_qa", cache=False)
    assert len(f.calls) == 2


def test_cache_key_covers_every_input(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"one")
    base = dict(stage="s", prompt_version="1", provider="p", model="m", prompt="x", images=[img],
                schema={"a": 1})
    k = client.cache_key(**base)
    assert k == client.cache_key(**base)
    for change in ({"stage": "t"}, {"prompt_version": "2"}, {"provider": "q"}, {"model": "n"},
                   {"prompt": "y"}, {"schema": {"a": 2}}, {"schema": None}):
        assert client.cache_key(**{**base, **change}) != k, change
    img.write_bytes(b"two")
    assert client.cache_key(**base) != k


def test_transport_retries_then_succeeds(env):
    install, sleeps, _ = env
    t = RawResponse(error_kind="transport", error="boom")
    f = Fake(t, t, ok(PLATE_OK))
    install(claude_cli=f)
    r = client.ask("plate_qa", "p", schema="plate_qa")
    assert r.attempts == 3 and sleeps == [5, 20]


def test_transport_exhausted_moves_to_next_member_then_unavailable(env):
    install, _, _ = env
    t = RawResponse(error_kind="transport", error="boom")
    f = Fake(t, t, t, t, t, t)      # plate_qa chain: sonnet then haiku, both on claude_cli
    install(claude_cli=f)
    with pytest.raises(LLMUnavailable) as e:
        client.ask("plate_qa", "p", schema="plate_qa")
    assert e.value.kind == "outage" and len(f.calls) == 6
    assert [c.model for c in f.calls][::3] == ["sonnet", "haiku"]


def test_schema_repair_round_appends_validator_errors(env):
    install, _, _ = env
    f = Fake(ok({"plates": "nope"}), ok(PLATE_OK))
    install(claude_cli=f)
    r = client.ask("plate_qa", "p", schema="plate_qa")
    assert r.data == PLATE_OK and r.attempts == 2
    assert "failed validation" in f.calls[1].prompt and "plates" in f.calls[1].prompt
    assert f.calls[0].prompt == "p"


def test_schema_invalid_after_repair_raises(env):
    install, _, _ = env
    bad = ok({"plates": "nope"})
    f = Fake(bad, bad, bad, bad)     # 2 chain members x (first + repair)
    install(claude_cli=f)
    with pytest.raises(LLMSchemaError):
        client.ask("plate_qa", "p", schema="plate_qa")
    assert len(f.calls) == 4


def test_adapter_revalidates_provider_structured_output(env):
    """A provider handing back `data` that violates the schema is rejected, not trusted."""
    install, _, _ = env
    f = Fake(ok({"plates": [{"n": 1, "fail": "explodes"}]}), ok(PLATE_OK))
    install(claude_cli=f)
    assert client.ask("plate_qa", "p", schema="plate_qa").attempts == 2


def test_text_stage_without_schema_and_empty_rejected(env):
    install, _, _ = env
    f = Fake(ok(text="  "), ok(text="hello"))
    install(claude_cli=f)
    r = client.ask("text_misc", "hi")
    assert r.text == "hello" and r.data is None and r.attempts == 2


def test_quota_sets_persisted_cooldown_and_skips_provider(env):
    install, _, tmp = env
    when = datetime.now(timezone.utc) + timedelta(hours=2)
    f = Fake(RawResponse(error_kind="quota", error="limit", retry_at=when))
    install(claude_cli=f)
    with pytest.raises(LLMUnavailable) as e:
        client.ask("text_misc", "p")
    assert e.value.kind == "quota" and abs((e.value.retry_at - when).total_seconds()) < 1
    state = json.loads((tmp / "llm_state.json").read_text())
    assert "claude_cli" in state["cooldown"]
    with pytest.raises(LLMUnavailable):
        client.ask("text_misc", "p2")
    assert len(f.calls) == 1        # second call never reached the provider


def test_quota_default_cooldown_is_one_hour(env):
    install, _, tmp = env
    install(claude_cli=Fake(RawResponse(error_kind="quota", error="limit")))
    with pytest.raises(LLMUnavailable):
        client.ask("text_misc", "p")
    until = datetime.fromisoformat(json.loads((tmp / "llm_state.json").read_text())["cooldown"]["claude_cli"])
    assert timedelta(minutes=59) < until - datetime.now(timezone.utc) <= timedelta(hours=1)


def test_expired_cooldown_is_ignored(env):
    install, _, tmp = env
    (tmp / "llm_state.json").write_text(json.dumps(
        {"cooldown": {"claude_cli": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}}))
    install(claude_cli=Fake(ok(text="fine")))
    assert client.ask("text_misc", "p").text == "fine"


def test_auth_raises_immediately_without_retry(env):
    install, sleeps, _ = env
    f = Fake(RawResponse(error_kind="auth", error="Not logged in"))
    install(claude_cli=f)
    with pytest.raises(LLMUnavailable) as e:
        client.ask("text_misc", "p")
    assert e.value.kind == "auth" and "claude_cli" in str(e.value) and not sleeps and len(f.calls) == 1


def test_disabled_providers_are_never_called(env, monkeypatch):
    install, _, _ = env
    cfg = client._config()
    cfg["providers"]["gemini"]["enabled"] = False
    cfg["chains"] = {"text_misc": ["gemini:gemini-2.5-flash"]}
    g = Fake()
    install(gemini=g)
    with pytest.raises(LLMUnavailable):
        client.ask("text_misc", "p")
    assert not g.calls


def test_shipped_config_defaults():
    cfg = load_config()
    assert cfg["defaults"]["provider"] == "claude_cli"
    assert cfg["providers"]["gemini"]["enabled"] is False and cfg["providers"]["openrouter"]["enabled"] is False
    assert stage_settings(cfg, "script_write")["chain"] == [("claude_cli", "opus")]
    assert stage_settings(cfg, "bench_judge")["chain"] == [("claude_cli", "opus")]
    assert "deepseek" not in json.dumps(cfg).lower()


@pytest.mark.parametrize("edit,msg", [
    (lambda c: c["stages"].update(bogus={"model": "x"}), "unknown stage"),
    (lambda c: c["stages"]["visual_plan"].update(provider="nope"), "undeclared provider"),
    (lambda c: c["providers"].update(x={"type": "deepseek"}), "invalid"),
    (lambda c: c["stages"]["bench_judge"].pop("model"), "pinned"),
    (lambda c: c.setdefault("chains", {}).update(plate_qa=["nope:x"]), "undeclared provider"),
])
def test_config_validation_fails_loudly(tmp_path, edit, msg):
    import yaml
    cfg = load_config()
    edit(cfg)
    p = tmp_path / "llm.yaml"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ConfigError, match=msg):
        load_config(p)


# ----------------------------------------------------------- claude cli --

def test_claude_envelope_fixture_pins_structured_output_field():
    """Recorded live envelope (claude 2.1.283, --json-schema): payload is `structured_output`."""
    raw = (FIX / "claude_cli_envelope_structured.json").read_text()
    r = ClaudeCLI.parse_output(raw, "", 0)
    assert r.error_kind is None and r.data == {"verdict": "PASS", "notes": "ok"}
    assert json.loads(r.text) == r.data and r.usage["cost_usd"] > 0 and r.usage["output_tokens"] > 0


def test_claude_error_envelopes_classified():
    reset = json.dumps({"is_error": True, "result": "You've hit your session limit · resets 7:30pm (UTC)"})
    r = ClaudeCLI.parse_output(reset, "", 1)
    assert r.error_kind == "quota" and r.retry_at and (r.retry_at.hour, r.retry_at.minute) == (19, 30)
    assert ClaudeCLI.parse_output(json.dumps({"is_error": True, "result": "Not logged in · Please run /login"}),
                                  "", 1).error_kind == "auth"
    assert ClaudeCLI.parse_output("", "connection reset", 1).error_kind == "transport"
    assert classify("weekly usage limit reached")[0] == "quota"


def test_parse_reset_rolls_to_tomorrow():
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
    assert parse_reset("resets 7:30pm (UTC)", now) == datetime(2026, 9, 29, 19, 30, tzinfo=timezone.utc)
    assert parse_reset("resets 9am (UTC)", now) == datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)
    assert parse_reset("no time here", now) is None


def test_claude_args_text_and_vision(tmp_path):
    c = ClaudeCLI({"bin": "claude", "fallback_model": "haiku"})
    req = RawRequest("", "p", [], {"type": "object"}, "sonnet", "medium", 10)
    a = c.build_args(req, tmp_path / "s.md", tmp_path)
    assert a[a.index("--tools") + 1] == "" and "--add-dir" not in a
    assert {"--no-session-persistence", "--strict-mcp-config", "--json-schema"} <= set(a)
    assert a[a.index("--fallback-model") + 1] == "haiku"
    dis = a[a.index("--disallowedTools") + 1]
    assert "WebFetch" in dis and "Skill" in dis
    v = c.build_args(RawRequest("", "p", [tmp_path / "i.png"], None, "haiku", "low", 10), tmp_path / "s.md", tmp_path)
    assert v[v.index("--tools") + 1] == "Read" and "--add-dir" in v
    assert "--fallback-model" not in v and "--json-schema" not in v   # same model as fallback -> omitted


def test_claude_complete_uses_fresh_cwd_and_stdin(monkeypatch, tmp_path):
    import subprocess
    seen = {}

    def fake_run(args, input, capture_output, text, cwd, timeout):
        seen.update(args=args, input=input, cwd=Path(cwd))
        assert Path(cwd) != Path.cwd() and Path(cwd).exists()
        img = [x for x in Path(cwd).iterdir() if x.name.startswith("image_")]
        assert img and img[0].read_bytes() == b"png"
        return subprocess.CompletedProcess(args, 0, (FIX / "claude_cli_envelope_structured.json").read_text(), "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    src = tmp_path / "in.png"
    src.write_bytes(b"png")
    r = ClaudeCLI({}).complete(RawRequest("", "hello", [src], None, "sonnet", "low", 5))
    assert r.error_kind is None and "hello" in seen["input"] and "image_1.png" in seen["input"]
    assert not seen["cwd"].exists()      # temp dir cleaned up


def test_claude_timeout_is_transport(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("claude", 1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert ClaudeCLI({}).complete(RawRequest("", "p", [], None, "sonnet", "low", 1)).error_kind == "transport"


def test_api_providers_without_key_report_auth(monkeypatch):
    from llm.providers.gemini import Gemini
    from llm.providers.openrouter import OpenRouter
    monkeypatch.setattr("llm.providers.gemini.env_key", lambda n: "")
    monkeypatch.setattr("llm.providers.openrouter.env_key", lambda n: "")
    req = RawRequest("", "p", [], None, "m", "low", 1)
    assert Gemini({}).complete(req).error_kind == "auth"
    assert OpenRouter({}).complete(req).error_kind == "auth"


# --------------------------------------------------------------- shims --

def test_director_shims_keep_legacy_contract(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "illustrated_engine"))
    from engine import director
    img = tmp_path / "s.png"
    img.write_bytes(b"x")
    seen = {}

    def fake_ask(stage, prompt, **kw):
        seen.update(stage=stage, **kw)
        from llm.types import LLMResult
        return LLMResult(kw.get("schema") and PLATE_OK, "```json\n{\"a\": 1,}\n```", stage, "p", "m", 1, 0.0, False)
    monkeypatch.setattr(director._llm, "ask", fake_ask)
    assert director.vision_ask(img, "q", stage="plate_qa") == PLATE_OK and seen["schema"] == "plate_qa"
    assert director.vision_ask(img, "q") == {"a": 1} and seen["stage"] == "vision_misc"   # tolerant parse ladder
    assert director.text_ask("hi", stage="fact_check").startswith("```") and seen["stage"] == "fact_check"

    def unavailable(stage, prompt, **kw):
        raise LLMUnavailable("down", "outage")
    monkeypatch.setattr(director._llm, "ask", unavailable)
    assert director.vision_ask(img, "q") is None and director.text_ask("hi") is None
