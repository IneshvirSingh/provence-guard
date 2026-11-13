from pathlib import Path

import pytest

from provguard.llm.providers import DEFAULT_PATH, ProviderError, ProviderRegistry

YAML = """
providers:
  groq:
    base_url: https://api.groq.com/openai/v1
    api_key_env: GROQ_API_KEY_TEST
    requires_payment_method: false
    models:
      openai/gpt-oss-120b:
        request_defaults: { reasoning_effort: low, parallel_tool_calls: false }
        limits: { rpm: 30, rpd: 1000, tpm: 8000, tpd: 200000 }
      meta-llama/llama-prompt-guard-2-86m:
        kind: classifier
        tool_calling: false
        limits: { rpm: 30, rpd: 14400, tpm: 15000, tpd: 500000 }
  parked:
    enabled: false
    base_url: https://z
    api_key_env: Z
    requires_payment_method: false
    models: { m: {} }
  unverified:
    base_url: https://x
    api_key_env: X
    models: { m: {} }
  paid:
    base_url: https://y
    api_key_env: Y
    requires_payment_method: true
    models: { m: {} }
"""


@pytest.fixture
def registry(tmp_path: Path) -> ProviderRegistry:
    p = tmp_path / "providers.yaml"
    p.write_text(YAML)
    return ProviderRegistry.load(p)


def test_resolve_verified_free_provider(registry: ProviderRegistry, monkeypatch):
    ref = registry.resolve("groq/openai/gpt-oss-120b")  # model IDs may themselves contain a slash
    assert ref.id == "groq/openai/gpt-oss-120b" and ref.limits.complete()
    assert ref.kind == "agent" and ref.request_defaults == {
        "reasoning_effort": "low",
        "parallel_tool_calls": False,
    }
    clf = registry.resolve("groq/meta-llama/llama-prompt-guard-2-86m")
    assert clf.kind == "classifier" and not clf.tool_calling and clf.request_defaults == {}
    with pytest.raises(ProviderError, match="not set"):
        ref.api_key()
    monkeypatch.setenv("GROQ_API_KEY_TEST", "k")
    assert ref.api_key() == "k"


@pytest.mark.parametrize(
    ("ref", "msg"),
    [
        ("groq", "provider/model"),
        ("nope/m", "not in config"),
        ("unverified/m", "not verified payment-free"),
        ("paid/m", "not verified payment-free"),
        ("groq/other", "not listed"),
        ("parked/m", "disabled"),
    ],
)
def test_refusals(registry: ProviderRegistry, ref, msg):
    with pytest.raises(ProviderError, match=msg):
        registry.resolve(ref)


def test_repo_config_loads():
    reg = ProviderRegistry.load(DEFAULT_PATH)
    assert "github_models" not in reg.providers  # retired 2026-07-30
    assert not reg.providers["gemini"].enabled
    groq = reg.providers["groq"]
    assert "llama-3.3-70b-versatile" not in groq.models  # retired for free accounts 2026-08-16
    assert all(m.limits.complete() for m in groq.models.values())
    assert groq.models["openai/gpt-oss-120b"].request_defaults["reasoning_effort"] == "low"
    assert groq.models["meta-llama/llama-prompt-guard-2-86m"].kind == "classifier"


LIVE = {"data": [{"id": "openai/gpt-oss-120b"}, {"id": "meta-llama/llama-prompt-guard-2-86m"}, {"id": "x"}]}


def test_check_models_passes_when_all_configured_ids_are_live(registry: ProviderRegistry, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY_TEST", "k")
    seen: list[tuple[str, dict[str, str]]] = []

    def fetch(url: str, headers):
        seen.append((url, dict(headers)))
        return LIVE

    assert registry.check_models("groq", fetch) == {
        "openai/gpt-oss-120b",
        "meta-llama/llama-prompt-guard-2-86m",
        "x",
    }
    assert seen == [("https://api.groq.com/openai/v1/models", {"Authorization": "Bearer k"})]


def test_check_models_fails_clearly_on_missing_id(registry: ProviderRegistry, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY_TEST", "k")
    with pytest.raises(ProviderError, match=r"not offered.*\['meta-llama/llama-prompt-guard-2-86m'\]"):
        registry.check_models("groq", lambda url, h: {"data": [{"id": "openai/gpt-oss-120b"}]})
    with pytest.raises(ProviderError, match="no model list"):
        registry.check_models("groq", lambda url, h: {"error": "nope"})


def test_check_models_needs_key_and_enabled_provider(registry: ProviderRegistry, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY_TEST", raising=False)
    with pytest.raises(ProviderError, match="not set"):
        registry.check_models("groq", lambda url, h: LIVE)
    with pytest.raises(ProviderError, match="disabled"):
        registry.check_models("parked", lambda url, h: LIVE)
    with pytest.raises(ProviderError, match="not in config"):
        registry.check_models("nope", lambda url, h: LIVE)
