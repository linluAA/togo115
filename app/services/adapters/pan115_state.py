from __future__ import annotations

import sys

from app.db import add_log as _add_log
from app.services import integration_state as _state


def _integration_attr(name: str):
    module = sys.modules.get("app.services.integrations")
    return getattr(module, name, None) if module is not None else None


def add_log(*args, **kwargs):
    func = _integration_attr("add_log") or _add_log
    return func(*args, **kwargs)


def get_setting(*args, **kwargs):
    func = _integration_attr("get_setting") or _state.get_setting
    return func(*args, **kwargs)


def save_setting(*args, **kwargs):
    func = _integration_attr("save_setting") or _state.save_setting
    return func(*args, **kwargs)


def get_flow(*args, **kwargs):
    func = _integration_attr("get_flow") or _state.get_flow
    return func(*args, **kwargs)


def save_flow(*args, **kwargs):
    func = _integration_attr("save_flow") or _state.save_flow
    return func(*args, **kwargs)


def module_proxy(*args, **kwargs):
    func = _integration_attr("module_proxy") or _state.module_proxy
    return func(*args, **kwargs)
