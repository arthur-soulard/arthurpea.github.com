"""
app.py — Point d'entree de Suivi PEA.

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
import notifications


APP_NAME    = "Suivi PEA"
APP_VERSION = "2.1.3"
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

    def open_data_folder(self) -> dict:
        """Ouvre le dossier des donnees dans l'Explorateur Windows."""
        try:
            path = str(storage.get_app_dir())
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

    # ─── Multi-profils ────────────────────────────────────────────────
    def get_profiles(self) -> dict:
        try:
            return {"ok": True, "state": storage.get_profiles_state()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_profile(self, label: str) -> dict:
        try:
            import re
            state = storage.get_profiles_state()
            base_slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "pea"
            slug = base_slug
            i = 2
            existing = {p["slug"] for p in state["profiles"]}
            while slug in existing:
                slug = f"{base_slug}_{i}"; i += 1
            state["profiles"].append({"slug": slug, "label": label or "Nouveau PEA"})
            storage.save_profiles_state(state)
            # Cree le dossier + un pea_data vierge
            storage.get_profile_dir(slug)
            from storage import default_data, save_data, get_profile_dir, DATA_FILE
            target = get_profile_dir(slug) / DATA_FILE
            if not target.exists():
                with open(target, "w", encoding="utf-8") as f:
                    import json as _json
                    _json.dump(default_data(), f, ensure_ascii=False, indent=2)
            return {"ok": True, "slug": slug}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def rename_profile(self, slug: str, label: str) -> dict:
        try:
            state = storage.get_profiles_state()
            for p in state["profiles"]:
                if p["slug"] == slug:
                    p["label"] = label or p["label"]
                    storage.save_profiles_state(state)
                    return {"ok": True}
            return {"ok": False, "error": "profil introuvable"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def delete_profile(self, slug: str) -> dict:
        try:
            state = storage.get_profiles_state()
            if len(state["profiles"]) <= 1:
                return {"ok": False, "error": "Impossible de supprimer le dernier profil"}
            state["profiles"] = [p for p in state["profiles"] if p["slug"] != slug]
            if state["active"] == slug:
                state["active"] = state["profiles"][0]["slug"]
            storage.save_profiles_state(state)
            return {"ok": True, "active": state["active"]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_active_profile(self, slug: str) -> dict:
        try:
            state = storage.get_profiles_state()
            if not any(p["slug"] == slug for p in state["profiles"]):
                return {"ok": False, "error": "profil inconnu"}
            state["active"] = slug
            storage.save_profiles_state(state)
            return {"ok": True}
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
        return {
            "appName":  APP_NAME,
            "version":  APP_VERSION,
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

def _startup_audit() -> None:
    """
    Ecrit un audit IMMEDIAT au demarrage dans %APPDATA%\\Suivi PEA\\startup_audit.log
    pour voir EXACTEMENT ce que voit le process au moment du lancement.
    """
    try:
        import datetime as _dt
        log_path = storage.get_app_dir() / "startup_audit.log"
        data_path = storage.get_data_path()

        # Lecture brute des 300 premiers octets (sans passer par load_data)
        first_bytes = ""
        try:
            if data_path.exists():
                with open(data_path, "rb") as f:
                    raw = f.read(300)
                first_bytes = raw.decode("utf-8", errors="replace")
        except Exception as e:
            first_bytes = f"<lecture KO: {e}>"

        with open(log_path, "a", encoding="utf-8") as log:
            log.write("\n" + "=" * 70 + "\n")
            log.write(f"STARTUP {_dt.datetime.now().isoformat()}\n")
            log.write(f"PID         : {os.getpid()}\n")
            log.write(f"sys.executable: {sys.executable}\n")
            log.write(f"sys.argv    : {sys.argv}\n")
            log.write(f"frozen      : {getattr(sys, 'frozen', False)}\n")
            log.write(f"_MEIPASS    : {getattr(sys, '_MEIPASS', None)}\n")
            log.write(f"cwd         : {os.getcwd()}\n")
            log.write(f"APPDATA env : {os.environ.get('APPDATA', '?')}\n")
            log.write(f"USERPROFILE : {os.environ.get('USERPROFILE', '?')}\n")
            log.write(f"app_dir     : {storage.get_app_dir()}\n")
            log.write(f"data_path   : {data_path}\n")
            log.write(f"data exists : {data_path.exists()}\n")
            if data_path.exists():
                st = data_path.stat()
                log.write(f"data size   : {st.st_size} octets\n")
                log.write(f"data mtime  : {_dt.datetime.fromtimestamp(st.st_mtime).isoformat()}\n")
            log.write(f"data first  : {first_bytes[:200]}\n")
            log.write(f"PYTHONIOENCODING: {os.environ.get('PYTHONIOENCODING', '?')}\n")
    except Exception as e:
        try:
            with open(storage.get_app_dir() / "startup_audit.log", "a", encoding="utf-8") as log:
                log.write(f"\nAUDIT FAILED: {e}\n")
        except Exception:
            pass


def main() -> int:
    install_crash_handler()
    # _startup_audit() retire — n'est plus necessaire

    # Lance la verification de mise a jour en arriere-plan (silencieux)
    try:
        import updater
        updater.start_check(APP_VERSION)
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
    saved_size = ui_prefs.get("windowSize")
    pos  = ui_prefs.get("windowPos")  # [x, y] ou None

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
    # - Si l'utilisateur a une taille sauvegardee → on la respecte (mais on clamp a la work area)
    # - Sinon (1er lancement) → on ouvre en quasi-plein-ecran (work area - 20px de marge)
    if saved_size and isinstance(saved_size, (list, tuple)) and len(saved_size) == 2:
        try:
            w_, h_ = int(saved_size[0]), int(saved_size[1])
            if not (200 <= w_ <= 8000 and 200 <= h_ <= 8000):
                w_, h_ = screen_w - 20, screen_h - 20
        except Exception:
            w_, h_ = screen_w - 20, screen_h - 20
    else:
        # Premier lancement : quasi-plein-ecran
        w_, h_ = screen_w - 20, screen_h - 20

    # Clamp final : ne depasse pas la work area
    w_ = min(w_, max(960, screen_w - 20))
    h_ = min(h_, max(640, screen_h - 20))
    size = (w_, h_)

    # Validation position : on rejette les valeurs aberrantes
    if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
        try:
            x_, y_ = int(pos[0]), int(pos[1])
            if not (-16000 < x_ < 16000 and -16000 < y_ < 16000):
                pos = None
            # On verifie aussi que la position est sur un ecran (pas perdue hors-bornes)
            elif x_ + w_ < 0 or y_ + h_ < 0 or x_ > screen_w or y_ > screen_h:
                pos = None
        except Exception:
            pos = None

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
            try:
                w_, h_ = int(window.width), int(window.height)
                # On refuse les tailles aberrantes (fenetre minimisee/cachee)
                if 200 <= w_ <= 8000 and 200 <= h_ <= 8000:
                    d["ui"]["windowSize"] = [w_, h_]
            except Exception:
                pass
            try:
                x_, y_ = int(window.x), int(window.y)
                # Valeurs Windows pour fenetre minimisee = -32000
                # On refuse aussi les positions hors ecran raisonnable
                if -16000 < x_ < 16000 and -16000 < y_ < 16000:
                    d["ui"]["windowPos"] = [x_, y_]
                else:
                    d["ui"]["windowPos"] = None  # rouvrir centre la prochaine fois
            except Exception:
                pass
            storage.save_data(d)
        except Exception as e:
            print(f"[app] Echec sauvegarde UI prefs : {e}", flush=True)

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
