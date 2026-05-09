"""
notifications.py — Notifications Windows toast natives.

Utilise win10toast si dispo (pip install win10toast). Si l'import echoue
(autre OS, lib non installee), les fonctions deviennent des no-ops silencieux,
pour ne jamais faire crasher l'app.

Les preferences sont lues depuis storage.load_data()['notifs'] :
  - bigMove   : alerte cours qui bouge > +/- 5%
  - dividend  : dividende prevu aujourd'hui
  - yahooDown : Yahoo injoignable
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

try:
    from win10toast import ToastNotifier  # type: ignore
    _toaster = ToastNotifier()
    _AVAILABLE = True
except Exception:
    _toaster = None
    _AVAILABLE = False


def _icon_path() -> Optional[str]:
    """Cherche l'icone .ico dans /assets pour les toasts (sinon icone par defaut)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "assets" / "icon.ico", here / "icon.ico"):
        if candidate.exists():
            return str(candidate)
    return None


def _show(title: str, msg: str, duration: int = 6) -> None:
    if not _AVAILABLE or _toaster is None:
        return
    icon = _icon_path()
    try:
        # threaded=True pour ne pas bloquer l'event loop pywebview
        _toaster.show_toast(
            title, msg,
            icon_path=icon,
            duration=duration,
            threaded=True,
        )
    except Exception as e:
        print(f"[notif] Echec toast : {e}", flush=True)


# ─── API publique ─────────────────────────────────────────────────────────────

def notify(title: str, msg: str, kind: str, prefs: dict) -> None:
    """
    Affiche une notif si l'utilisateur l'a activee.
      kind : 'bigMove' | 'dividend' | 'yahooDown' | 'info'
      prefs : dict de preferences (depuis pea_data.json -> notifs)
    """
    if kind != "info" and not prefs.get(kind, False):
        return
    threading.Thread(target=_show, args=(title, msg), daemon=True).start()


def is_available() -> bool:
    return _AVAILABLE
