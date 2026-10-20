"""Verification backends (one per specification language)."""

from src.backends.dafny_backend import DafnyBackend
from src.backends.python_contract_backend import PythonContractBackend
from src.schemas import Language

_SHARED: dict = {}


def get_backend(language: Language):
    """Return a process-wide backend instance so result caches are shared."""
    if language not in _SHARED:
        _SHARED[language] = (DafnyBackend() if language is Language.DAFNY
                             else PythonContractBackend())
    return _SHARED[language]


__all__ = ["DafnyBackend", "PythonContractBackend", "get_backend"]
