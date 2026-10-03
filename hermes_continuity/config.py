"""Settings, read from ``plugins.entries.continuity.settings`` in the profile's config.yaml."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    "enabled": False,                   # its own turns; perception, the standing view and the journal work either way
    "view": True,                       # hand every turn a frame of the standing view
    "platform": "",
    "session_key": "",
    "outreach": False,
    "quiet_hours": "22:00-08:00",
    "max_outreach_per_day": 3,
    "max_steps_per_day": 30,
    "energy_per_event": 1.0,
    "step_cost": 0.34,
    "energy_max": 3.0,
    "min_pull": 0.45,
    "chain_decay": 0.75,
    "associate_k": 3,
    "item_ttl_minutes": 120,
    "settle_seconds": 20,
    "full_frame_every": 6,
    "sophia_path": "",
    "poll_seconds": 5,                  # how often the loop re-checks its conditions; never a reason to wake the model
}


def coerce(key: str, value: Any) -> Any:
    default = DEFAULTS[key]
    if value is None:
        return default
    try:
        if isinstance(default, bool):
            return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(value)
        if isinstance(default, float):
            return float(value)
        return str(value)
    except (TypeError, ValueError):
        return default


def load(get: Optional[Callable[..., Any]] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``get``: ``ctx.get_config`` (plugin-relative keys)."""
    cfg = dict(DEFAULTS)
    if get is not None:
        for k in DEFAULTS:
            try:
                cfg[k] = coerce(k, get(k, default=DEFAULTS[k]))
            except Exception:
                cfg[k] = DEFAULTS[k]
    for k, v in (overrides or {}).items():
        if k in DEFAULTS:
            cfg[k] = coerce(k, v)
    return cfg


def in_quiet_hours(spec: str, hour_minute: str) -> bool:
    """``spec`` like "22:00-08:00" (may wrap past midnight); ``hour_minute`` like "23:15"."""
    try:
        start, end = [s.strip() for s in (spec or "").split("-", 1)]
    except ValueError:
        return False
    if not start or not end or start == end:
        return False
    return (start <= hour_minute < end) if start < end else (hour_minute >= start or hour_minute < end)
