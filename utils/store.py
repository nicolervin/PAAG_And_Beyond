"""Backward-compatible facade for modular domain-driven persistence stores."""

from __future__ import annotations

import sys as _sys
import types as _types

from utils import db_core as _db_core
from utils import project_store as _project_store
from utils import assembly_store as _assembly_store
from utils import ergonomics_store as _ergonomics_store
from utils import safety_store as _safety_store
from utils import yamazumi_store as _yamazumi_store
from utils import process_store as _process_store
from utils import fishbone_store as _fishbone_store
from utils import model_part_store as _model_part_store

_DOMAIN_MODULES = [
    _project_store,
    _assembly_store,
    _ergonomics_store,
    _safety_store,
    _yamazumi_store,
    _process_store,
    _fishbone_store,
    _model_part_store,
]

_db_core.sync_store_runtime()


def _facade_exports() -> dict[str, object]:
    exports = {
        name: value
        for name, value in vars(_db_core).items()
        if not name.startswith("__")
        and name not in {
            "_DOMAIN_MODULES", "_DOMAIN_EXPORTS", "_functools", "_importlib",
            "_sys", "_types",
        }
    }
    for module in _DOMAIN_MODULES:
        for name in module.__domain_exports__:
            exports[name] = getattr(module, name)
    return exports


_EXPORTED = _facade_exports()
globals().update(_EXPORTED)


class _StoreFacade(_types.ModuleType):
    """Propagate facade monkeypatches to the modules that execute the code."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name not in globals().get("_EXPORTED", {}):
            return
        if hasattr(_db_core, name):
            setattr(_db_core, name, value)
        for module in _DOMAIN_MODULES:
            module.__dict__[name] = value


_sys.modules[__name__].__class__ = _StoreFacade
__all__ = sorted(_EXPORTED)
