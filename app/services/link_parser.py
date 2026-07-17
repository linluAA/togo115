from __future__ import annotations

"""Compatibility shim: prefer app.services.link."""

from importlib import import_module as _import_module

_mod = _import_module("app.services.link")
globals().update({name: getattr(_mod, name) for name in dir(_mod) if name != "__all__"})
__all__ = [name for name in globals() if not name.startswith("__")]
