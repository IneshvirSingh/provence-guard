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
      llama-3.3-70b-versatile: { limits: { rpm: 30, rpd: 1000, tpm: 6000, tpd: 100000 } }
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
    ref = registry.resolve("groq/llama-3.3-70b-versatile")
    assert ref.id == "groq/llama-3.3-70b-versatile" and ref.limits.complete()
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
    ],
)
def test_refusals(registry: ProviderRegistry, ref, msg):
    with pytest.raises(ProviderError, match=msg):
        registry.resolve(ref)


def test_repo_config_loads_and_limits_are_still_pending():
    reg = ProviderRegistry.load(DEFAULT_PATH)
    assert "groq" in reg.providers
    assert "github_models" not in reg.providers  # retired 2026-07-30
