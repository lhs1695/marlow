import keyline
from keyline.runner import load_tasks


def test_keyline_package_imports() -> None:
    assert keyline.__doc__
    assert load_tasks() == []
