"""Backward-compatible facade for modular domain-driven persistence stores."""

from __future__ import annotations

import importlib as _importlib
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
from utils import recycle_bin_store as _recycle_bin_store
from utils import feedback_store as _feedback_store

_DOMAIN_MODULE_NAMES = (
    "utils.project_store",
    "utils.assembly_store",
    "utils.ergonomics_store",
    "utils.safety_store",
    "utils.yamazumi_store",
    "utils.process_store",
    "utils.fishbone_store",
    "utils.model_part_store",
    "utils.recycle_bin_store",
    "utils.feedback_store",
)

_DOMAIN_MODULES = [
    _project_store,
    _assembly_store,
    _ergonomics_store,
    _safety_store,
    _yamazumi_store,
    _process_store,
    _fishbone_store,
    _model_part_store,
    _recycle_bin_store,
    _feedback_store,
]

_REFRESHING = False


def _prepare_and_register_domain_module(mod: _types.ModuleType) -> None:
    if mod.__name__ == "utils.recycle_bin_store":
        for _rb_export_name in mod.__domain_exports__:
            _rb_obj = getattr(mod, _rb_export_name, None)
            if (
                callable(_rb_obj)
                and not getattr(_rb_obj, "_is_domain_entrypoint", False)
                and _rb_export_name not in {
                    "init_recycle_bin_schema",
                    "capture_deletion_to_recycle_bin",
                }
            ):
                setattr(mod, _rb_export_name, _db_core.domain_entrypoint(_rb_obj))
    elif mod.__name__ == "utils.feedback_store":
        for _fb_export_name in mod.__domain_exports__:
            _fb_obj = getattr(mod, _fb_export_name, None)
            if (
                callable(_fb_obj)
                and not getattr(_fb_obj, "_is_domain_entrypoint", False)
                and _fb_export_name not in {
                    "init_feedback_schema",
                }
            ):
                setattr(mod, _fb_export_name, _db_core.domain_entrypoint(_fb_obj))
    _db_core.register_domain_module(mod, mod.__domain_exports__)


for _idx, _dom_mod in enumerate(_DOMAIN_MODULES):
    if _dom_mod.__name__ not in {
        "utils.recycle_bin_store",
        "utils.feedback_store",
    } and not getattr(_dom_mod, "_DOMAIN_REGISTERED_V2", False):
        _DOMAIN_MODULES[_idx] = _importlib.reload(_dom_mod)
    _prepare_and_register_domain_module(_DOMAIN_MODULES[_idx])

_DOMAIN_MODULE_MAP: dict[str, _types.ModuleType] = {
    _m.__name__: _m for _m in _DOMAIN_MODULES
}
_db_core.sync_store_runtime()


def _refresh_domain_modules() -> None:
    """Re-bind domain modules if Streamlit's file watcher evicted or reloaded any submodule."""
    global _db_core, _DOMAIN_MODULES, _DOMAIN_MODULE_MAP, _REFRESHING
    if _REFRESHING:
        return
    _REFRESHING = True
    try:
        _db_core = _importlib.import_module("utils.db_core")
        refreshed: list[_types.ModuleType] = []
        for mod_name in _DOMAIN_MODULE_NAMES:
            mod = _importlib.import_module(mod_name)
            refreshed.append(mod)
            _prepare_and_register_domain_module(mod)
        _DOMAIN_MODULES = refreshed
        _DOMAIN_MODULE_MAP = {m.__name__: m for m in refreshed}
        _db_core.sync_store_runtime(force=True)
    finally:
        _REFRESHING = False


def _ensure_fresh_domain_modules() -> None:
    """Refresh domain modules only when sys.modules indicates a submodule was evicted or replaced."""
    if _REFRESHING:
        return
    if _sys.modules.get("utils.db_core") is not _db_core:
        _refresh_domain_modules()
        return
    for mod_name, cached_mod in _DOMAIN_MODULE_MAP.items():
        if _sys.modules.get(mod_name) is not cached_mod:
            _refresh_domain_modules()
            return


def _facade_exports() -> dict[str, object]:
    exports = {
        name: value
        for name, value in vars(_db_core).items()
        if not name.startswith("__")
        and name not in {
            "_DOMAIN_MODULES", "_DOMAIN_EXPORTS", "_REGISTERED_ENTRYPOINT_FUNCTIONS",
            "_functools", "_importlib",
            "_sys", "_types",
        }
    }
    for module in _DOMAIN_MODULES:
        for name in module.__domain_exports__:
            exports[name] = getattr(module, name)
    return exports


_EXPORTED = _facade_exports()
_FACADE_BASELINE = dict(_EXPORTED)
globals().update(_EXPORTED)


def __getattr__(name: str) -> object:
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    _ensure_fresh_domain_modules()
    if name in _EXPORTED:
        return _EXPORTED[name]
    _refresh_domain_modules()
    if name in _EXPORTED:
        return _EXPORTED[name]
    for module in _DOMAIN_MODULES:
        if hasattr(module, name):
            val = getattr(module, name)
            globals()[name] = val
            _EXPORTED[name] = val
            _FACADE_BASELINE.setdefault(name, val)
            return val
    if hasattr(_db_core, name):
        val = getattr(_db_core, name)
        globals()[name] = val
        _EXPORTED[name] = val
        _FACADE_BASELINE.setdefault(name, val)
        return val
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


class _StoreFacade(_types.ModuleType):
    """Propagate facade monkeypatches to the modules that execute the code."""

    def __getattribute__(self, name: str) -> object:
        if not name.startswith("_"):
            d = object.__getattribute__(self, "__dict__")
            if not d.get("_REFRESHING", False):
                ensure_fn = d.get("_ensure_fresh_domain_modules")
                if callable(ensure_fn):
                    ensure_fn()
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> object:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
        _ensure_fresh_domain_modules()
        if name in globals().get("_EXPORTED", {}):
            return globals()["_EXPORTED"][name]
        _refresh_domain_modules()
        if name in globals().get("_EXPORTED", {}):
            return globals()["_EXPORTED"][name]
        for module in _DOMAIN_MODULES:
            if hasattr(module, name):
                val = getattr(module, name)
                self.__dict__[name] = val
                globals().setdefault("_EXPORTED", {})[name] = val
                globals().setdefault("_FACADE_BASELINE", {}).setdefault(name, val)
                return val
        if hasattr(_db_core, name):
            val = getattr(_db_core, name)
            self.__dict__[name] = val
            globals().setdefault("_EXPORTED", {})[name] = val
            globals().setdefault("_FACADE_BASELINE", {}).setdefault(name, val)
            return val
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name not in globals().get("_EXPORTED", {}):
            return
        globals()["_EXPORTED"][name] = value
        if hasattr(_db_core, name):
            setattr(_db_core, name, value)
        for module in _DOMAIN_MODULES:
            module.__dict__[name] = value
        if name in ("DB_PATH", "connection", "query", "execute"):
            clear_fn = getattr(_db_core, "clear_all_caches", None)
            if callable(clear_fn):
                clear_fn()
        rev = _db_core.bump_runtime_revision()
        _db_core._SYNCED_REVISION = rev


_sys.modules[__name__].__class__ = _StoreFacade
_db_core.sync_store_runtime(force=True)
__all__ = sorted(_EXPORTED)
