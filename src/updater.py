"""
updater.py — Verifieur de mise a jour silencieux.

Lance un thread daemon qui interroge l'API GitHub Releases au demarrage.
Le resultat est lu ensuite via get_result() depuis le bridge Python<->JS.
"""
from __future__ import annotations

import json
import threading
import urllib.request

RELEASES_API = "https://api.github.com/repos/arthur-soulard/arthurpea.github.com/releases/latest"

_lock = threading.Lock()
_state: dict = {"checked": False, "hasUpdate": False, "version": None, "url": None}


def _parse_ver(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


def _fetch(current: str) -> None:
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={
                "User-Agent": "Suivi-PEA-Updater/2",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        tag = data.get("tag_name", "")
        latest = tag.lstrip("v")
        url = data.get("html_url", "")
        has_update = bool(latest) and _parse_ver(latest) > _parse_ver(current)
        with _lock:
            _state.update({"checked": True, "hasUpdate": has_update, "version": latest, "url": url})
    except Exception:
        with _lock:
            _state["checked"] = True


def start_check(current_version: str) -> None:
    threading.Thread(target=_fetch, args=(current_version,), daemon=True).start()


def get_result() -> dict:
    with _lock:
        return dict(_state)
