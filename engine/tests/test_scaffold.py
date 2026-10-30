import sys


def test_engine_scaffold_uses_supported_python():
    assert sys.version_info >= (3, 11)
