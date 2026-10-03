"""Mindscape: the Hermes dashboard tab for watching and curating Sophia's memory.

Mounted by the dashboard at ``/api/plugins/sophia/`` (the plugin must be listed in ``plugins.enabled``). Reads go
through ``observe`` on short-lived read-only connections; every change goes through a ``Store`` method that
journals it with its reason and a way back.
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

PKG_DIR = Path(__file__).resolve().parent.parent
_ALIAS = "sophia_mindscape_pkg"


def _pkg(sub: str):
    """Import a module of this plugin's package under a private name (the dashboard loads this file on its own,
    outside the package; the memory provider's own import is left alone)."""
    if _ALIAS not in sys.modules:
        spec = importlib.util.spec_from_file_location(_ALIAS, PKG_DIR / "__init__.py",
                                                      submodule_search_locations=[str(PKG_DIR)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_ALIAS] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module(f"{_ALIAS}.{sub}")


O = _pkg("observe")
router = APIRouter()


def _home() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home())


def _ctx():
    home = _home()
    engine = _pkg("engine")
    cfg = _pkg("config").load_config(str(home))
    path = engine.default_db_path(str(home))
    if not path.exists():
        raise HTTPException(404, f"No Sophia store for this profile ({path}). Is memory.provider set to sophia?")
    return cfg, path


def _store(path: Path):
    return _pkg("store").Store(path)


@router.get("/now")
def now() -> Dict[str, Any]:
    cfg, path = _ctx()
    return O.now_state(path, cfg)


@router.get("/overview")
def overview() -> Dict[str, Any]:
    cfg, path = _ctx()
    return {**O.overview(path, cfg), "user": cfg.get("user_name"), "agent": cfg.get("agent_name")}


@router.get("/queue")
def queue(plans: int = 12) -> Dict[str, Any]:
    cfg, path = _ctx()
    return O.queue(path, cfg, plans=max(1, min(plans, 200)))


@router.get("/journal")
def journal(night: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    _, path = _ctx()
    return O.journal(path, night, max(1, min(limit, 1000)))


@router.get("/graph")
def graph() -> Dict[str, Any]:
    cfg, path = _ctx()
    return O.graph(path, cfg)


@router.get("/entities")
def entities(q: str = "") -> Dict[str, Any]:
    cfg, path = _ctx()
    return O.entities(path, cfg, q)


@router.get("/entity/{key:path}")
def entity(key: str) -> Dict[str, Any]:
    cfg, path = _ctx()
    out = O.entity(path, cfg, key)
    if out is None:
        raise HTTPException(404, f"no entity {key!r}")
    return out


@router.get("/recall")
def recall(limit: int = 60, before: Optional[float] = None) -> Dict[str, Any]:
    cfg, path = _ctx()
    return O.recall_list(path, cfg, max(1, min(limit, 500)), before)


@router.get("/recall/{inj_id}")
def recall_detail(inj_id: str) -> Dict[str, Any]:
    cfg, path = _ctx()
    out = O.recall_detail(path, cfg, inj_id)
    if out is None:
        raise HTTPException(404, "no such recall")
    return out


# ------------------------------------------------------------------ curation (journaled, undoable)
class Undo(BaseModel):
    journal_id: int


class Plan(BaseModel):
    fact_id: str
    outcome: str                       # happened | didnt
    reason: str = ""


class Review(BaseModel):
    item: str                          # 'j:<journal id>' or 'f:<fact id>'
    note: str = ""


class Correct(BaseModel):
    action: str                        # relabel | retract | drop
    reason: str
    window_id: Optional[str] = None
    fact_id: Optional[str] = None
    to: Optional[str] = None


@router.post("/undo")
def undo(body: Undo) -> Dict[str, Any]:
    _, path = _ctx()
    s = _store(path)
    try:
        what = s.undo_journal(body.journal_id, by="dashboard")
    finally:
        s.close()
    if not what:
        raise HTTPException(409, "nothing to undo (or already undone)")
    return {"ok": True, "undone": what}


@router.post("/plan")
def plan(body: Plan) -> Dict[str, Any]:
    if body.outcome not in ("happened", "didnt"):
        raise HTTPException(400, "outcome must be 'happened' or 'didnt'")
    _, path = _ctx()
    s = _store(path)
    try:
        changed = s.resolve_plan(body.fact_id, body.outcome, body.reason, by="dashboard")
        jid = s.last_journal_id if changed else None
    finally:
        s.close()
    return {"ok": changed, "journal_id": jid}


@router.post("/review")
def review(body: Review) -> Dict[str, Any]:
    if not body.item or ":" not in body.item:
        raise HTTPException(400, "item must look like 'j:<id>' or 'f:<id>'")
    _, path = _ctx()
    s = _store(path)
    try:
        s.mark_reviewed(body.item, body.note, by="dashboard")
        jid = s.last_journal_id
    finally:
        s.close()
    return {"ok": True, "journal_id": jid}


@router.post("/correct")
def correct(body: Correct) -> Dict[str, Any]:
    if not body.reason.strip():
        raise HTTPException(400, "a reason is required")
    _, path = _ctx()
    ids: List[str] = O.window_ref(path, body.window_id) if body.window_id else []
    s = _store(path)
    try:
        if body.action == "relabel":
            if not ids or not (body.to or "").strip():
                raise HTTPException(400, "relabel needs window_id and to")
            n = s.relabel_speaker(ids, body.to.strip(), body.reason, by="dashboard")
        elif body.action == "drop":
            if not ids:
                raise HTTPException(400, "drop needs window_id")
            n = s.drop_windows(ids, body.reason, by="dashboard")
        elif body.action == "retract":
            if not body.fact_id:
                raise HTTPException(400, "retract needs fact_id")
            n = int(s.retract_fact(body.fact_id, body.reason, by="dashboard"))
        else:
            raise HTTPException(400, "action must be relabel, drop or retract")
        jid = s.last_journal_id if n else None
    finally:
        s.close()
    return {"ok": bool(n), "changed": n, "journal_id": jid}


# ---------------------------------------------------------------- continuity
# The companion plugin's state, for watching it (on a test profile first). It isn't scoped to the dashboard's
# profile: every profile that has a continuity store can be chosen.
_CONT_ALIAS = "continuity_dash_pkg"


def _continuity(sub: str):
    if _CONT_ALIAS not in sys.modules:
        for cand in (PKG_DIR.parent / "hermes_continuity", _root() / "plugins" / "continuity"):
            if (cand / "__init__.py").exists():
                spec = importlib.util.spec_from_file_location(_CONT_ALIAS, cand / "__init__.py",
                                                              submodule_search_locations=[str(cand)])
                mod = importlib.util.module_from_spec(spec)
                sys.modules[_CONT_ALIAS] = mod
                spec.loader.exec_module(mod)
                break
        else:
            raise HTTPException(404, "The continuity companion isn't installed next to Sophia")
    return importlib.import_module(f"{_CONT_ALIAS}.{sub}")


def _root() -> Path:
    home = _home()
    return home.parent.parent if home.parent.name == "profiles" else home


def _continuity_homes() -> Dict[str, Path]:
    root = _root()
    found = {"default": root} if (root / "plugin-data" / "continuity" / "continuity.db").exists() else {}
    for p in sorted((root / "profiles").glob("*")) if (root / "profiles").is_dir() else []:
        if (p / "plugin-data" / "continuity" / "continuity.db").exists():
            found[p.name] = p
    return found


def _continuity_settings(home: Path):
    try:
        import yaml
        cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
        settings = ((cfg.get("plugins") or {}).get("entries") or {}).get("continuity", {}).get("settings") or {}
    except Exception:
        settings = {}
    return lambda key, default=None: settings.get(key, default)


@router.get("/continuity")
def continuity(profile: str = "") -> Dict[str, Any]:
    homes = _continuity_homes()
    if not homes:
        return {"profiles": [], "profile": None, "report": None}
    current = _home().name if _home().parent.name == "profiles" else "default"
    name = profile if profile in homes else current if current in homes else next(iter(homes))
    home = homes[name]
    cfg = _continuity("config").load(_continuity_settings(home))
    try:
        user = _pkg("config").load_config(str(home))["user_name"]
    except Exception:
        user = "the user"
    rep = _continuity("report").build(home / "plugin-data" / "continuity" / "continuity.db", cfg, user=user)
    return {"profiles": list(homes), "profile": name, "report": rep}
