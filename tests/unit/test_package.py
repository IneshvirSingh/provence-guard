import provguard
import provguard.core


def test_version_is_set() -> None:
    assert provguard.__version__


def test_core_exports_the_public_api() -> None:
    assert {"Plan", "PlanRunner", "PolicySet", "TrustConfig", "decide"} <= set(provguard.core.__all__)
