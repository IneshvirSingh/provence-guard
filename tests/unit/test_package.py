import provguard
import provguard.core


def test_version_is_set() -> None:
    assert provguard.__version__


def test_core_is_importable() -> None:
    assert provguard.core.__all__ == []
