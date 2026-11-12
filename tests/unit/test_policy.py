from pathlib import Path

import pytest
from pydantic import ValidationError

from provguard.core.policy import ArgPolicy, Decision, PolicySet, decide, entry_matches
from provguard.core.provenance import PLANNER, SYSTEM, USER, scalar, tool, wrap

ROOT = Path(__file__).resolve().parents[2]
TX = tool("get_most_recent_transactions", True)
TX_MEMO = tool("get_most_recent_transactions", False)
RF = tool("read_file", False)
UI = tool("get_user_info", True)


@pytest.fixture(scope="module")
def banking() -> PolicySet:
    return PolicySet.load(ROOT / "policies" / "banking.yaml")


def test_entry_matches_never_matches_untrusted():
    assert entry_matches("USER", USER) and entry_matches("tool:read_file", tool("read_file", True))
    assert not entry_matches("tool:read_file", RF)
    assert not entry_matches("USER", tool("read_file", True)) and not entry_matches("PLANNER", USER)


def test_bad_allow_entry_rejected():
    with pytest.raises(ValidationError):
        ArgPolicy(allow=["untrusted:read_file"])


SUBJECT = scalar("Refund", PLANNER)
DATE = scalar("2022-04-01", PLANNER)


def _send(recipient, amount, subject=SUBJECT, date=DATE):
    return {"recipient": recipient, "amount": amount, "subject": subject, "date": date}


def test_refund_from_ledger_fields_is_allowed(banking: PolicySet):
    d = decide(banking, "send_money", _send(scalar("GB29NWBK60161331926819", USER), scalar(4.0, TX, USER)))
    assert d.verdict == "ALLOW" and d.allowed and all(r.outcome == "ALLOW" for r in d.reasons)
    assert d.policy_version == 1


def test_recipient_from_file_is_confirmed_with_explanation(banking: PolicySet):
    d = decide(banking, "send_money", _send(scalar("UK12345678901234567890", RF), scalar(98.7, RF)))
    assert d.verdict == "CONFIRM"
    reason = next(r for r in d.reasons if r.arg == "recipient")
    assert reason.rule == "send_money.recipient" and "tool:read_file(untrusted)" in reason.sources
    assert Decision.model_validate_json(d.model_dump_json()) == d


def test_amount_selected_by_memo_is_confirmed(banking: PolicySet):
    d = decide(
        banking, "send_money", _send(scalar("SE3550000000054910000003", TX), scalar(50.0, TX, TX_MEMO))
    )
    assert d.verdict == "CONFIRM" and [r.arg for r in d.reasons if r.outcome == "CONFIRM"] == ["amount"]


def test_profile_data_cannot_flow_into_memo(banking: PolicySet):
    d = decide(
        banking,
        "send_money",
        _send(scalar("GB29NWBK60161331926819", USER), scalar(1.0, USER), subject=scalar("pw", UI)),
    )
    assert d.verdict == "CONFIRM" and d.reasons[2].arg == "subject"


def test_planner_invented_recipient_is_confirmed_but_amount_ok(banking: PolicySet):
    d = decide(banking, "send_money", _send(scalar("DE89370400440532013000", PLANNER), scalar(5.0, PLANNER)))
    assert d.verdict == "CONFIRM" and [r.arg for r in d.reasons if r.outcome != "ALLOW"] == ["recipient"]


def test_constraints_deny_malformed_values(banking: PolicySet):
    d = decide(banking, "send_money", _send(scalar("Spotify", USER), scalar(5.0, USER)))
    assert d.verdict == "DENY" and d.reasons[0].message.startswith("value 'Spotify'")
    d = decide(banking, "send_money", _send(scalar("GB29NWBK60161331926819", USER), scalar(0, USER)))
    assert d.verdict == "DENY"
    d = decide(banking, "send_money", _send(scalar("GB29NWBK60161331926819", USER), scalar("ten", USER)))
    assert d.verdict == "DENY"


def test_deny_beats_confirm(banking: PolicySet):
    d = decide(banking, "send_money", _send(scalar("Spotify", RF), scalar(5.0, RF)))
    assert d.verdict == "DENY"
    assert {r.outcome for r in d.reasons} == {"DENY", "CONFIRM", "ALLOW"}


def test_password_only_from_user(banking: PolicySet):
    assert decide(banking, "update_password", {"password": scalar("1j1l-2k3j", USER)}).verdict == "ALLOW"
    assert decide(banking, "update_password", {"password": scalar("x", PLANNER)}).verdict == "DENY"
    assert decide(banking, "update_password", {"password": scalar("x", RF)}).verdict == "DENY"


def test_user_info_default_and_absent_optional_args(banking: PolicySet):
    assert decide(banking, "update_user_info", {"street": scalar("Elm", USER)}).verdict == "ALLOW"
    d = decide(banking, "update_user_info", {"street": scalar("Dalton", RF)})
    assert d.verdict == "CONFIRM" and d.reasons[0].rule == "update_user_info.street"


def test_update_scheduled_id_from_ledger(banking: PolicySet):
    ok = decide(
        banking,
        "update_scheduled_transaction",
        {"id": scalar(7, tool("get_scheduled_transactions", True)), "amount": scalar(2200, USER)},
    )
    assert ok.verdict == "ALLOW"
    bad = decide(
        banking,
        "update_scheduled_transaction",
        {"id": scalar(7, tool("get_scheduled_transactions", False)), "amount": scalar(2200, USER)},
    )
    assert bad.verdict == "CONFIRM"


def test_unguarded_and_unlisted(banking: PolicySet):
    assert decide(banking, "read_file", {"file_path": scalar("x", RF)}).verdict == "ALLOW"
    d = decide(banking, "delete_everything", {})
    assert d.verdict == "DENY" and d.reasons[0].rule == "unlisted_tool"
    lax = PolicySet(version=2, unlisted_tool="CONFIRM")
    assert decide(lax, "whatever", {}).verdict == "CONFIRM"


def test_guarded_tool_without_default_uses_user_only():
    ps = PolicySet(version=1, tools={"t": {"guarded": True}})
    assert decide(ps, "t", {"a": scalar(1, USER)}).verdict == "ALLOW"
    assert decide(ps, "t", {"a": scalar(1, SYSTEM)}).verdict == "CONFIRM"


def test_structured_argument_uses_all_sources(banking: PolicySet):
    arg = wrap({"a": [1, 2]}, {USER})
    assert decide(banking, "update_user_info", {"city": arg}).verdict == "ALLOW"


def test_enum_and_maximum_constraints():
    ps = PolicySet.model_validate(
        {
            "version": 1,
            "tools": {
                "t": {
                    "args": {
                        "k": {
                            "allow": ["USER"],
                            "constraints": {"enum": ["a", "b"]},
                            "on_violation": "CONFIRM",
                        },
                        "n": {"allow": ["USER"], "constraints": {"maximum": 10}},
                    }
                }
            },
        }
    )
    assert decide(ps, "t", {"k": scalar("a", USER), "n": scalar(10, USER)}).verdict == "ALLOW"
    assert decide(ps, "t", {"k": scalar("z", USER)}).verdict == "CONFIRM"
    assert decide(ps, "t", {"n": scalar(11, USER)}).verdict == "DENY"
