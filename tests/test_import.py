import pytest

pytestmark = pytest.mark.unit


def test_import() -> None:
    import oh_llm  # noqa: F401
