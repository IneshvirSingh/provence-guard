import json

import pytest

from provguard.llm.client import LLMClient
from provguard.llm.providers import Limits, ModelRef

REF = ModelRef(
    provider="groq", model="openai/gpt-oss-120b", base_url="https://x", api_key_env="X", limits=Limits()
)


def reply(content):
    text = content if isinstance(content, str) else json.dumps(content)
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class Scripted:
    """Transport that answers planner calls from `plans` and extractor calls from `extractions`, in order."""

    def __init__(self, plans=(), extractions=()):
        self.plans = list(plans)
        self.extractions = list(extractions)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        system = payload["messages"][0]["content"]
        if system.startswith("You are a planner"):
            return reply(self.plans.pop(0))
        assert system.startswith("You extract"), system[:40]
        return reply(self.extractions.pop(0))


@pytest.fixture
def make_client():
    def _make(transport):
        return LLMClient(REF, transport=transport)

    return _make
