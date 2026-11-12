from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from provguard.core.provenance import USER, select, tool
from provguard.core.trust import TrustConfig

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def trust() -> TrustConfig:
    return TrustConfig.load(ROOT / "policies" / "trust.yaml")


class Tx(BaseModel):
    id: int
    amount: float
    subject: str


def test_per_field_override_inside_lists(trust: TrustConfig):
    out = trust.label_output("get_most_recent_transactions", [Tx(id=1, amount=5.0, subject="memo")])
    assert select(out, "[0].amount").all_sources() == {tool("get_most_recent_transactions", True)}
    subject = select(
        out, "[0].subject"
    )  # the record's own (trusted) source is pushed down; untrusted dominates
    assert tool("get_most_recent_transactions", False) in subject.all_sources() and not subject.is_trusted()
    assert not out.is_trusted() and select(out, "amount").is_trusted()


def test_untrusted_tool_and_echo(trust: TrustConfig):
    out = trust.label_output("read_file", "Dear tenant", [USER])
    assert out.all_sources() == {tool("read_file", False), USER}
    msg = trust.label_output("send_money", {"message": "sent"}, [tool("read_file", False)])
    assert tool("read_file", False) in out.all_sources() and msg.all_sources() >= {tool("send_money", True)}


def test_unlisted_tool_gets_default(trust: TrustConfig):
    out = trust.label_output("mystery", {"a": [1, None, object()]})
    assert out.all_sources() == {tool("mystery", False)}
    assert out.plain()["a"][:2] == [1, None]


def test_trusted_default_and_strict_schema():
    cfg = TrustConfig.model_validate({"version": 1, "default": "trusted"})
    assert cfg.label_output("x", 1).is_trusted()
    with pytest.raises(ValidationError):
        TrustConfig.model_validate({"version": 1, "tools": {"x": {"trusted": True, "bogus": 1}}})
