"""
app.py — Point d'entree de Pilote.

Lance :
  - le serveur Yahoo Finance en arriere-plan (server.py)
  - une fenetre native (pywebview) qui charge l'UI HTML
  - un bridge Python <-> JavaScript pour les acces stockage / cours / notifs

Tout s'arrete proprement quand la fenetre se ferme.
Une seule instance autorisee : si l'app est deja lancee, on ramene la fenetre
existante au premier plan et on quitte.
"""
from __future__ import annotations

import os
import sys
import json
import socket
import threading
import traceback
from pathlib import Path
from typing import Optional

import webview                        # pywebview

import server
import storage
import finances
import sports
import pret
import patrimoine
import sante
import sauvegarde
import notifications


APP_NAME    = "Pilote"
APP_VERSION = "4.1.4"
SINGLE_INSTANCE_PORT = 50317          # port arbitraire pour le verrou single-instance
WINDOW_DEFAULT_SIZE  = (1280, 800)
WINDOW_MIN_SIZE      = (960, 640)


# ─── Single instance ──────────────────────────────────────────────────────────

_lock_socket = None  # type: Optional[socket.socket]


def acquire_single_instance_lock() -> bool:
    """
    Tente de binder un port localhost. Si reussi -> on est la seule instance.
    Si echoue -> une autre instance tourne deja, on lui dit de remonter au front.
    """
    global _lock_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(5)
        _lock_socket = s
        # Thread d'ecoute : si une 2eme instance se connecte -> on remonte au front
        threading.Thread(target=_listen_for_focus_pings, args=(s,), daemon=True).start()
        return True
    except OSError:
        # Deja en cours -> on ping pour faire remonter la fenetre existante
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
                c.settimeout(2)
                c.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
                c.sendall(b"focus")
        except Exception:
            pass
        return False


def _listen_for_focus_pings(server_sock: socket.socket) -> None:
    while True:
        try:
            conn, _ = server_sock.accept()
            try:
                conn.recv(64)
            except Exception:
                pass
            conn.close()
            # Ramene la fenetre principale au premier plan
            try:
                w = webview.windows[0] if webview.windows else None
                if w is not None:
                    w.restore()
                    w.show()
                    # Force le focus (Windows)
                    try:
                        import ctypes
                        hwnd = ctypes.windll.user32.GetForegroundWindow()
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            return


# ─── Bridge JS <-> Python ─────────────────────────────────────────────────────

class Api:
    """
    Methodes appelees depuis JavaScript via window.pywebview.api.<methode>(...)
    Toutes retournent des objets JSON-serialisables.
    """

    def __init__(self):
        self._notif_prefs = {}

    # -- Stockage ----------------------------------------------------------

    def load_data(self) -> dict:
        try:
            data = storage.load_data()
            self._notif_prefs = data.get("notifs", {})
            # Hydrate le serveur avec le cache disque -> mode hors-ligne
            cache = data.get("_cache", {})
            server.hydrate_cache(cache.get("prices", {}), cache.get("history", {}))
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def save_data(self, data: dict) -> dict:
        try:
            # Met a jour le cache cours avant ecriture, pour le mode hors-ligne
            data.setdefault("_cache", {})
            cache = server.dump_cache()
            data["_cache"]["prices"]  = cache["prices"]  or data["_cache"].get("prices",  {})
            data["_cache"]["history"] = cache["history"] or data["_cache"].get("history", {})
            storage.save_data(data)
            self._notif_prefs = data.get("notifs", {})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_ui_prefs(self, prefs: dict) -> dict:
        """
        Methode dediee : ecrit UNIQUEMENT uiPrefs dans le fichier sans toucher
        au reste. Utilisee pour le PIN, l'accent, etc. — robuste contre les
        ecrasements concurrents.
        """
        try:
            d = storage.load_data()
            d["uiPrefs"] = prefs or {}
            storage.save_data(d)
            return {"ok": True, "uiPrefs": d["uiPrefs"]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- Finances perso (propre a l'utilisateur actif) --------------------

    def load_finances(self) -> dict:
        try:
            return {"ok": True, "data": finances.load_data()}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def save_finances(self, data: dict) -> dict:
        try:
            finances.save_data(data or {})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- Sports (propre a l'utilisateur actif) ----------------------------

    def load_sports(self) -> dict:
        try:
            return {"ok": True, "data": sports.load_data(),
                    "catalog": sports.SPORTS, "fieldCatalog": sports.FIELD_CATALOG}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def save_sports(self, data: dict) -> dict:
        try:
            sports.save_data(data or {})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- Pret etudiant (propre a l'utilisateur actif) ----------------------

    def load_pret(self) -> dict:
        try:
            return {"ok": True, "data": pret.load_data()}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def save_pret(self, data: dict) -> dict:
        try:
            pret.save_data(data or {})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- Patrimoine (propre a l'utilisateur actif) -------------------------

    def load_patrimoine(self) -> dict:
        try:
            data = patrimoine.load_data()
            return {"ok": True, "data": data, "types": patrimoine.TYPES,
                    "moisCourant": patrimoine.mois_courant(),
                    "moisSaisi":   patrimoine.mois_saisi(data),
                    "net":         patrimoine.net_worth(data),
                    "serie":       patrimoine.serie_mensuelle(data)}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def save_patrimoine(self, data: dict) -> dict:
        try:
            patrimoine.save_data(data or {})
            d = patrimoine.load_data()
            return {"ok": True, "net": patrimoine.net_worth(d),
                    "serie": patrimoine.serie_mensuelle(d),
                    "moisSaisi": patrimoine.mois_saisi(d)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- Sante (propre a l'utilisateur actif) ------------------------------

    def load_sante(self) -> dict:
        try:
            return {"ok": True, "data": sante.load_data(),
                    "metrics": sante.METRICS}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def save_sante(self, data: dict) -> dict:
        try:
            sante.save_data(data or {})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sante_ocr_available(self) -> dict:
        try:
            return sante.ocr_available()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sante_pick_screenshots(self) -> dict:
        """Selecteur de captures FitDays (plusieurs a la fois)."""
        try:
            win = webview.windows[0]
            result = win.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=("Images (*.png;*.jpg;*.jpeg;*.heic)", "All files (*.*)"),
            )
            if not result:
                return {"ok": False, "cancelled": True}
            paths = list(result) if isinstance(result, (list, tuple)) else [result]
            return {"ok": True, "paths": paths}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sante_read_screenshots(self, paths: list) -> dict:
        """
        Lecture OCR des captures. Peut prendre plusieurs secondes : l'UI
        affiche un indicateur pendant ce temps.
        """
        try:
            return sante.read_screenshots(list(paths or []))
        except Exception as e:
            return {"ok": False, "error": str(e), "values": {},
                    "trace": traceback.format_exc()}

    # -- Sauvegarde externe (cle USB) --------------------------------------
    # Au niveau de l'installation, pas de l'utilisateur : une sauvegarde
    # embarque TOUT le dossier Donnees, tous les espaces confondus.

    def sauvegarde_status(self) -> dict:
        try:
            return sauvegarde.status()
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def sauvegarde_set_config(self, patch: dict) -> dict:
        """Met a jour les seuls champs de comportement (auto, frequence, keep)."""
        try:
            cfg = sauvegarde.load_config()
            for key in ("auto", "frequence", "keep"):
                if key in (patch or {}):
                    cfg[key] = patch[key]
            cfg["keep"] = max(1, min(100, int(cfg.get("keep") or 10)))
            if cfg.get("frequence") not in ("daily", "weekly", "manual"):
                cfg["frequence"] = "daily"
            sauvegarde.save_config(cfg)
            return sauvegarde.status()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sauvegarde_pick_folder(self) -> dict:
        """Ouvre le selecteur de dossier et retient la cle choisie."""
        try:
            win = webview.windows[0]
            result = win.create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return {"ok": False, "cancelled": True}
            path = result[0] if isinstance(result, (list, tuple)) else result
            res = sauvegarde.set_destination(path)
            if not res.get("ok"):
                return res
            return sauvegarde.status()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sauvegarde_use_drive(self, root: str) -> dict:
        """Choisit une cle detectee, avec un sous-dossier dedie."""
        try:
            target = os.path.join(root, "Sauvegardes Pilote")
            res = sauvegarde.set_destination(target)
            if not res.get("ok"):
                return res
            return sauvegarde.status()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sauvegarde_push_usb(self, root: str = None) -> dict:
        """Miroir immediat du dossier Donnees sur la cle (bouton de l'accueil)."""
        try:
            return sauvegarde.push_to_usb(root)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sauvegarde_usb_state(self) -> dict:
        try:
            return sauvegarde.usb_state()
        except Exception as e:
            return {"ok": False, "error": str(e), "drives": [], "count": 0}

    def sauvegarde_run(self) -> dict:
        try:
            return sauvegarde.run_backup(reason="manuel")
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sauvegarde_list(self) -> dict:
        try:
            return sauvegarde.list_backups()
        except Exception as e:
            return {"ok": False, "error": str(e), "backups": []}

    def sauvegarde_restore(self, path: str) -> dict:
        try:
            return sauvegarde.restore_from(path)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sauvegarde_open_folder(self) -> dict:
        try:
            dest = sauvegarde.resolve_destination()
            if not dest.get("ready"):
                return {"ok": False, "error": dest.get("message") or "Destination absente."}
            if sys.platform == "win32":
                os.startfile(dest["path"])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", dest["path"]])
            return {"ok": True, "path": dest["path"]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_data_folder(self) -> dict:
        """Ouvre le dossier de donnees de l'utilisateur actif."""
        try:
            path = str(storage.get_user_dir())
            if sys.platform == "win32":
                os.startfile(path)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- Cours / historique ------------------------------------------------

    def get_prices(self, tickers: list) -> dict:
        try:
            return {"ok": True, "prices": server.get_prices(tickers)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_history(self, tickers: list) -> dict:
        try:
            return {"ok": True, "history": server.get_history(tickers)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def server_port(self) -> int:
        return server.get_port()

    # -- Export / import (boutons UI) -------------------------------------

    def export_dialog(self) -> dict:
        win = webview.windows[0]
        result = win.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="pea_data.json",
            file_types=("JSON (*.json)",),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        target = result if isinstance(result, str) else result[0]
        ok = storage.export_to(target)
        return {"ok": ok, "path": target}

    def import_dialog(self) -> dict:
        win = webview.windows[0]
        result = win.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("JSON (*.json)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        ok, msg = storage.import_from(path)
        return {"ok": ok, "message": msg}

    def import_legacy(self, payload: dict) -> dict:
        ok, msg = storage.import_from_legacy(payload)
        return {"ok": ok, "message": msg}

    # -- Fenetre / divers --------------------------------------------------

    def open_app_folder(self) -> dict:
        path = str(storage.get_app_dir())
        try:
            os.startfile(path)
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def minimize(self):
        try:
            webview.windows[0].minimize()
        except Exception:
            pass

    def maximize_toggle(self):
        """
        Maximisation 'a la Windows' (respecte la barre des taches), meme
        sur fenetre frameless et ecran HiDPI.
        On utilise SetWindowPos directement (pixels physiques, DPI-aware) plutot
        que pywebview.resize qui peut mal gerer le scaling.
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            # Force la conscience DPI au niveau process (per-monitor v2)
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
            except Exception:
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
                except Exception:
                    pass

            hwnd = user32.GetForegroundWindow()

            # Si deja "maximise", on restaure
            if getattr(self, "_is_max", False):
                r = getattr(self, "_pre_max_rect", None)
                if r:
                    SWP_NOZORDER   = 0x0004
                    SWP_SHOWWINDOW = 0x0040
                    user32.SetWindowPos(
                        hwnd, 0,
                        int(r[0]), int(r[1]), int(r[2]), int(r[3]),
                        SWP_NOZORDER | SWP_SHOWWINDOW
                    )
                self._is_max = False
                return

            # Memorise la position/taille actuelle (pixels reels via GetWindowRect)
            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                            ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
            cur = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(cur))
            self._pre_max_rect = (
                cur.left, cur.top,
                cur.right - cur.left, cur.bottom - cur.top
            )

            # Trouve le moniteur et sa work area
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize",    wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork",    RECT),
                    ("dwFlags",   wintypes.DWORD),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(monitor, ctypes.byref(mi))

            wa = mi.rcWork
            wa_l, wa_t = wa.left, wa.top
            wa_w, wa_h = wa.right - wa.left, wa.bottom - wa.top

            # SetWindowPos en pixels physiques (DPI-aware)
            SWP_NOZORDER   = 0x0004
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(
                hwnd, 0,
                wa_l, wa_t, wa_w, wa_h,
                SWP_NOZORDER | SWP_SHOWWINDOW
            )

            self._is_max = True
        except Exception as e:
            print(f"[maximize_toggle] {e}", flush=True)

    def close(self):
        try:
            webview.windows[0].destroy()
        except Exception:
            pass

    def notify(self, title: str, msg: str, kind: str = "info") -> dict:
        notifications.notify(title, msg, kind, self._notif_prefs)
        return {"ok": True}

    # ─── Multi-utilisateurs ────────────────────────────────
    # Un utilisateur = un dossier complet (PEA + comptes + sport + pret).

    def get_users(self) -> dict:
        try:
            return {"ok": True, "state": server.with_pin_flags(storage.get_users_state())}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_user(self, label: str, emoji: str = "", color: str = "") -> dict:
        try:
            label = (label or "").strip() or "Nouvel utilisateur"
            state = storage.get_users_state()
            slug = storage.slugify(label, [u["slug"] for u in state["users"]])
            state["users"].append({"slug": slug, "label": label,
                                   "emoji": (emoji or "").strip(),
                                   "color": (color or "").strip()})
            storage.save_users_state(state)
            # Cree le dossier : les modules ecriront leurs defauts au 1er acces
            storage.get_user_dir(slug)
            return {"ok": True, "slug": slug, "state": state}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def update_user(self, slug: str, label: str = None,
                    emoji: str = None, color: str = None) -> dict:
        try:
            state = storage.get_users_state()
            for u in state["users"]:
                if u["slug"] == slug:
                    if label is not None and label.strip():
                        u["label"] = label.strip()
                    if emoji is not None:
                        u["emoji"] = emoji.strip()
                    if color is not None:
                        u["color"] = color.strip()
                    storage.save_users_state(state)
                    return {"ok": True, "state": state}
            return {"ok": False, "error": "utilisateur introuvable"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def delete_user(self, slug: str) -> dict:
        """Retire l'utilisateur de la liste. Son dossier reste sur le disque."""
        try:
            state = storage.get_users_state()
            if len(state["users"]) <= 1:
                return {"ok": False, "error": "Impossible de supprimer le dernier utilisateur"}
            state["users"] = [u for u in state["users"] if u["slug"] != slug]
            if state["active"] == slug:
                state["active"] = state["users"][0]["slug"]
            storage.save_users_state(state)
            return {"ok": True, "active": state["active"], "state": state,
                    "folder": str(storage.get_app_dir() / storage.USERS_DIRNAME / slug)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_active_user(self, slug: str) -> dict:
        try:
            state = storage.get_users_state()
            if not any(u["slug"] == slug for u in state["users"]):
                return {"ok": False, "error": "utilisateur inconnu"}
            state["active"] = slug
            storage.save_users_state(state)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─── Icone de l'app a la couleur du theme ──────────────────────

    def set_app_icon_color(self, color: str) -> dict:
        """Recolore l'icone de la fenetre + barre des taches (effet immediat)."""
        try:
            import appicon
            return {"ok": appicon.apply_to_window(color)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def apply_icon_to_shortcuts(self, color: str) -> dict:
        """Repointe aussi les raccourcis Bureau / Demarrer / barre des taches."""
        try:
            import appicon
            return appicon.apply_to_shortcuts(color)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_update(self) -> dict:
        try:
            import updater
            return {"ok": True, **updater.get_result()}
        except Exception as e:
            return {"ok": False, "error": str(e), "checked": True, "hasUpdate": False}

    def recheck_update(self) -> dict:
        """Relance une verification de mise a jour (utilise par le bouton manuel)."""
        try:
            import updater
            updater.start_check(APP_VERSION)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def start_update(self) -> dict:
        try:
            import updater
            updater.start_install_async()   # non-bloquant, progression via get_install_progress()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_install_progress(self) -> dict:
        try:
            import updater
            return {"ok": True, **updater.get_progress()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_url(self, url: str) -> dict:
        try:
            import webbrowser
            webbrowser.open(url)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def app_info(self) -> dict:
        try:
            active = storage.get_active_user()
        except Exception:
            active = {}
        return {
            "appName":  APP_NAME,
            "version":  APP_VERSION,
            "user":     active,
            "appDir":   str(storage.get_app_dir()),
            "dataPath": str(storage.get_data_path()),
            "logPath":  str(storage.get_log_path()),
            "port":     server.get_port(),
            "notifAvailable": notifications.is_available(),
        }


# ─── Localisation des assets (fonctionne dev + PyInstaller) ───────────────────

def resource_path(rel: str) -> str:
    """
    Sert pour PyInstaller : en mode 'frozen', les fichiers sont extraits dans
    sys._MEIPASS. En dev, on prend le dossier du fichier app.py.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return str(Path(base) / rel)
    return str(Path(__file__).resolve().parent / rel)


# ─── Crash log silencieux ─────────────────────────────────────────────────────

CRASH_LOG_MAX = 256 * 1024   # 256 Ko


def _rotate_crash_log() -> None:
    """
    Un crash.log qui grossit sans fin finit par peser plus lourd que les
    donnees elles-memes et par partir dans chaque sauvegarde USB. On garde la
    generation precedente sous crash.log.1 et on repart a zero au-dela de
    CRASH_LOG_MAX.
    """
    try:
        path = storage.get_log_path()
        if path.exists() and path.stat().st_size > CRASH_LOG_MAX:
            prev = path.with_name(path.name + ".1")
            try:
                if prev.exists():
                    prev.unlink()
            except Exception:
                pass
            path.replace(prev)
    except Exception:
        pass



def install_crash_handler() -> None:
    """
    Installe un crash handler silencieux qui n'ecrit que les VRAIS crashes.
    Filtre les erreurs benignes connues (ex: bug WPARAM de win10toast).
    """
    BENIGN = ("WPARAM is simple", "win10toast")

    def _is_benign(exc) -> bool:
        try:
            return any(b in str(exc) for b in BENIGN)
        except Exception:
            return False

    def _hook(exc_type, exc, tb):
        if _is_benign(exc):
            return  # ignore silencieusement les bugs connus de libs tierces
        try:
            _rotate_crash_log()
            with open(storage.get_log_path(), "a", encoding="utf-8") as f:
                f.write("\n=== CRASH ===\n")
                import datetime as _dt
                f.write(_dt.datetime.now().isoformat() + "\n")
                import traceback as _tb
                _tb.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook

    # Filtre aussi les exceptions levees dans des threads (toast tourne dans un thread)
    try:
        def _thread_hook(args):
            if _is_benign(args.exc_value):
                return
            sys.excepthook(args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = _thread_hook
    except Exception:
        pass


# ─── Cycle de vie ─────────────────────────────────────────────────────────────


def main() -> int:
    install_crash_handler()

    # Le PIN, global jusqu'a la v4.1.3, devient propre a chaque utilisateur
    try:
        storage.migrate_legacy_pin()
    except Exception as e:
        print(f"[app] migration PIN KO : {e}", flush=True)

    # Lance la verification de mise a jour en arriere-plan (silencieux)
    try:
        import updater
        updater.start_check(APP_VERSION)
    except Exception:
        pass

    # Sauvegarde externe automatique, en arriere-plan et sans rien bloquer :
    # si la cle USB n'est pas branchee, on note le statut et on n'insiste pas.
    def _auto_sauvegarde():
        try:
            res = sauvegarde.auto_backup_if_due()
            if res.get("ok"):
                print(f"[app] sauvegarde externe : {res.get('path')}", flush=True)
        except Exception as e:
            print(f"[app] sauvegarde auto KO : {e}", flush=True)

    try:
        threading.Thread(target=_auto_sauvegarde, daemon=True).start()
    except Exception:
        pass

    # Active la conscience DPI au plus tot (avant de creer la fenetre).
    # Ca evite les soucis de tailles sur ecran HiDPI (laptops 4K, etc.).
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()  # legacy
                except Exception:
                    pass

    # Single instance : si une autre tourne, on quitte (elle a deja remonte au front)
    if not acquire_single_instance_lock():
        print("[app] Une autre instance tourne deja. Sortie.", flush=True)
        return 0

    # Charge les preferences UI pour decider taille/position fenetre
    data = storage.load_data()
    ui_prefs = data.get("ui", {})
    saved_size      = ui_prefs.get("windowSize")
    saved_maximized = ui_prefs.get("windowMaximized", True)   # True = defaut = plein ecran
    pos             = ui_prefs.get("windowPos")  # [x, y] ou None

    # Recupere la work area du moniteur principal (ecran moins barre des taches)
    screen_w, screen_h = 1280, 720  # fallback
    try:
        if sys.platform == "win32":
            import ctypes
            user32 = ctypes.windll.user32
            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            wa = _RECT()
            if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(wa), 0):
                screen_w = wa.right - wa.left
                screen_h = wa.bottom - wa.top
    except Exception:
        pass

    # Strategie d'ouverture :
    # - windowMaximized == True (defaut 1er lancement) → plein ecran work-area exacte
    # - Sinon → taille sauvegardee (clampee)
    if saved_maximized or not (saved_size and isinstance(saved_size, (list, tuple)) and len(saved_size) == 2):
        w_, h_ = screen_w, screen_h
        pos = None  # pas de position sauvegardee en mode plein ecran
    else:
        try:
            w_, h_ = int(saved_size[0]), int(saved_size[1])
            if not (200 <= w_ <= 8000 and 200 <= h_ <= 8000):
                w_, h_ = screen_w, screen_h
        except Exception:
            w_, h_ = screen_w, screen_h
        # Clamp final
        w_ = min(w_, max(960, screen_w))
        h_ = min(h_, max(640, screen_h))
        # Validation position
        if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                x_, y_ = int(pos[0]), int(pos[1])
                if not (-16000 < x_ < 16000 and -16000 < y_ < 16000):
                    pos = None
                elif x_ + w_ < 0 or y_ + h_ < 0 or x_ > screen_w or y_ > screen_h:
                    pos = None
            except Exception:
                pos = None
        else:
            pos = None

    size = (w_, h_)

    api = Api()
    html_path = resource_path(os.path.join("ui", "index.html"))

    # Demarre le serveur Yahoo + sert le HTML
    port = server.start_server(html_path=html_path)

    # Attend que le serveur reponde vraiment avant d'ouvrir la fenetre
    import time as _time
    for _ in range(40):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _probe:
                _probe.settimeout(0.2)
                if _probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
        except Exception:
            pass
        _time.sleep(0.05)

    # L'UI est servie par le serveur local : pas de file://, pas de query string,
    # le port se lit naturellement via location.port.
    url = f"http://127.0.0.1:{port}/"

    window_kwargs = dict(
        title=APP_NAME,
        url=url,
        js_api=api,
        width=size[0],
        height=size[1],
        min_size=WINDOW_MIN_SIZE,
        resizable=True,
        text_select=True,
        confirm_close=False,
        frameless=True,         # titlebar custom dans l'UI
        easy_drag=False,        # le drag est gere via -webkit-app-region: drag
    )
    if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
        window_kwargs["x"] = int(pos[0])
        window_kwargs["y"] = int(pos[1])

    window = webview.create_window(**window_kwargs)

    # Sauvegarde de la taille/position avant fermeture
    def _on_closing():
        try:
            d = storage.load_data()
            d.setdefault("ui", {})

            # Taille reelle via ctypes (gere le maximize ctypes qui bypass window.width)
            actual_w = actual_h = actual_x = actual_y = None
            try:
                import ctypes as _ct
                from ctypes import wintypes as _wt
                _u32 = _ct.windll.user32
                _hwnd = _u32.GetForegroundWindow()
                class _R(_ct.Structure):
                    _fields_ = [("left", _wt.LONG), ("top", _wt.LONG),
                                ("right", _wt.LONG), ("bottom", _wt.LONG)]
                _wr = _R()
                if _u32.GetWindowRect(_hwnd, _ct.byref(_wr)):
                    actual_w = _wr.right - _wr.left
                    actual_h = _wr.bottom - _wr.top
                    actual_x = _wr.left
                    actual_y = _wr.top
            except Exception:
                pass

            # Fallback pywebview si ctypes echoue
            if actual_w is None:
                try:
                    actual_w, actual_h = int(window.width), int(window.height)
                    actual_x, actual_y = int(window.x), int(window.y)
                except Exception:
                    pass

            # Detecte si la fenetre couvre >= 95 % de la work area → maximisee
            maximized = False
            try:
                import ctypes as _ct2
                from ctypes import wintypes as _wt2
                class _R2(_ct2.Structure):
                    _fields_ = [("left", _wt2.LONG), ("top", _wt2.LONG),
                                ("right", _wt2.LONG), ("bottom", _wt2.LONG)]
                _wa = _R2()
                if _ct2.windll.user32.SystemParametersInfoW(0x0030, 0, _ct2.byref(_wa), 0):
                    wa_w = _wa.right - _wa.left
                    wa_h = _wa.bottom - _wa.top
                    if actual_w and actual_h and wa_w > 0 and wa_h > 0:
                        maximized = (actual_w >= wa_w * 0.95 and actual_h >= wa_h * 0.95)
            except Exception:
                pass

            d["ui"]["windowMaximized"] = maximized
            if maximized:
                d["ui"]["windowSize"] = None
                d["ui"]["windowPos"]  = None
            else:
                if actual_w and 200 <= actual_w <= 8000 and \
                   actual_h and 200 <= actual_h <= 8000:
                    d["ui"]["windowSize"] = [actual_w, actual_h]
                if actual_x is not None and -16000 < actual_x < 16000 and \
                   actual_y is not None and -16000 < actual_y < 16000:
                    d["ui"]["windowPos"] = [actual_x, actual_y]
                else:
                    d["ui"]["windowPos"] = None

            storage.save_data(d)
        except Exception as e:
            print(f"[app] Echec sauvegarde UI prefs : {e}", flush=True)

    # Icone recoloree selon l'accent choisi : des que la fenetre existe
    def _paint_icon():
        try:
            import appicon
            accent = (storage.load_data().get("uiPrefs") or {}).get("accent")
            appicon.apply_to_window(accent or appicon.DEFAULT_COLOR)
        except Exception as e:
            print(f"[app] icone accent KO : {e}", flush=True)

    try:
        window.events.shown += _paint_icon
    except Exception:
        pass

    window.events.closing += _on_closing

    try:
        # debug=False pour la prod ; True pour ouvrir les devtools
        webview.start(debug=False)
    finally:
        # Apres fermeture de la fenetre : on coupe le serveur, on libere le port
        server.stop_server()
        try:
            if _lock_socket is not None:
                _lock_socket.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
