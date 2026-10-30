"""Filters for the templates: dates the way people read them."""
from .dates import to_local


def nice_date(moment):
    """Oct 30, 2026 (written by hand: %-d doesn't work on Windows)."""
    local = to_local(moment)
    return f"{local:%b} {local.day}, {local.year}"


def nice_datetime(moment):
    """Oct 30, 2026, 2:30 PM"""
    local = to_local(moment)
    return f"{nice_date(moment)}, {local.hour % 12 or 12}:{local:%M %p}"


def input_datetime(moment):
    """The value a <input type="datetime-local"> wants: 2026-10-30T14:30"""
    return f"{to_local(moment):%Y-%m-%dT%H:%M}" if moment else ""


def init_app(app):
    app.jinja_env.filters["nice_date"] = nice_date
    app.jinja_env.filters["nice_datetime"] = nice_datetime
    app.jinja_env.filters["input_datetime"] = input_datetime
