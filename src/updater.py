"""
updater.py — Verifieur et installateur de mise a jour avec progression et logs.

Tous les evenements sont logges dans %APPDATA%\\Suivi PEA\\update.log
pour permettre de diagnostiquer toute panne d'auto-update.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

RELEASES_API = "https://api.github.com/repos/arthur-soulard/arthurpea.github.com/releases/latest"

_lock = threading.Lock()

_state: dict = {
    "checked": False,
    "hasUpdate": False,
    "version": None,
    "url": None,
    "downloadUrl": None,
}

_progress: dict = {"step": "idle", "pct": 0, "error": None}


# ── Logs ──────────────────────────────────────────────────────────────────────

def _log_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    p = Path(base) / "Suivi PEA"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p / "update.log"


def _log(msg: str) -> None:
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ver(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


def _set_progress(step: str, pct: int, error: str | None = None) -> None:
    with _lock:
        _progress.update({"step": step, "pct": pct, "error": error})
    _log(f"PROGRESS step={step} pct={pct} error={error}")


# ── Check update ──────────────────────────────────────────────────────────────

def _fetch(current: str) -> None:
    try:
        _log(f"CHECK current_version={current}")
        req = urllib.request.Request(
            RELEASES_API,
            headers={"User-Agent": "Suivi-PEA-Updater/2", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())

        tag = data.get("tag_name", "")
        latest = tag.lstrip("v")
        html_url = data.get("html_url", "")
        has_update = bool(latest) and _parse_ver(latest) > _parse_ver(current)

        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name", "").endswith("Setup.exe"):
                download_url = asset.get("browser_download_url")
                break

        with _lock:
            _state.update({
                "checked": True,
                "hasUpdate": has_update,
                "version": latest,
                "url": html_url,
                "downloadUrl": download_url,
            })
        _log(f"CHECK OK latest={latest} hasUpdate={has_update} downloadUrl={download_url}")
    except Exception as e:
        _log(f"CHECK FAIL: {e}\n{traceback.format_exc()}")
        with _lock:
            _state["checked"] = True


def start_check(current_version: str) -> None:
    threading.Thread(target=_fetch, args=(current_version,), daemon=True).start()


def get_result() -> dict:
    with _lock:
        return dict(_state)


# ── Install with progress ────────────────────────────────────────────────────

def get_progress() -> dict:
    with _lock:
        return dict(_progress)


def start_install_async() -> None:
    """Lance l'installation dans un thread — retourne immediatement."""
    _log("INSTALL: thread starting")
    _set_progress("downloading", 0)
    threading.Thread(target=_do_install, daemon=True).start()


def _do_install() -> None:
    try:
        with _lock:
            download_url = _state.get("downloadUrl")
            version = _state.get("version")

        _log(f"INSTALL: starting v{version} from {download_url}")

        if not download_url:
            _set_progress("error", 0, "URL de téléchargement introuvable (recheck nécessaire)")
            return

        exe_path = sys.executable
        _log(f"INSTALL: exe_path={exe_path} frozen={getattr(sys, 'frozen', False)}")

        tmp_dir = Path(tempfile.gettempdir()) / "suivi_pea_update"
        tmp_dir.mkdir(exist_ok=True)
        setup_path = tmp_dir / "Suivi_PEA_Setup.exe"
        _log(f"INSTALL: setup_path={setup_path}")

        # ── Étape 1 : Téléchargement (0 → 70%) ──────────────────────────────
        _set_progress("downloading", 1)
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "Suivi-PEA-Updater/2"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            total = int(r.headers.get("Content-Length", 0))
            estimated = total or (25 * 1024 * 1024)  # fallback 25 Mo
            _log(f"INSTALL: download total={total} estimated={estimated}")
            downloaded = 0
            chunk_size = 65536  # 64 Ko
            last_logged_pct = 0
            with open(setup_path, "wb") as f:
                while True:
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = min(69, int(downloaded / estimated * 70))
                    pct = max(1, pct)  # toujours montrer >= 1% pour ne pas paraître bloqué
                    _set_progress("downloading", pct)
                    if pct - last_logged_pct >= 10:
                        _log(f"INSTALL: downloaded {downloaded} bytes ({pct}%)")
                        last_logged_pct = pct

        size = setup_path.stat().st_size
        _log(f"INSTALL: download done, file size={size}")

        if size < 1024 * 1024:  # < 1 Mo = corrompu
            _set_progress("error", 0, f"Téléchargement corrompu ({size} octets)")
            return

        # ── Étape 2 : Préparation batch (70 → 80%) ───────────────────────────
        _set_progress("installing", 75)

        bat_path = tmp_dir / "update.bat"
        bat_content = (
            f'@echo off\r\n'
            f'echo [%TIME%] Update batch started >> "{tmp_dir / "update_bat.log"}"\r\n'
            f':wait\r\n'
            f'tasklist /FI "IMAGENAME eq Suivi_PEA.exe" 2>nul | find /I "Suivi_PEA.exe" > nul\r\n'
            f'if not errorlevel 1 ( timeout /t 1 /nobreak > nul & goto wait )\r\n'
            f'echo [%TIME%] App closed, running installer >> "{tmp_dir / "update_bat.log"}"\r\n'
            f'"{setup_path}" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES\r\n'
            f'echo [%TIME%] Installer finished (errorlevel=%errorlevel%) >> "{tmp_dir / "update_bat.log"}"\r\n'
            f'(goto) 2>nul & del "%~f0"\r\n'
        )
        bat_path.write_text(bat_content, encoding="ascii", errors="replace")
        _log(f"INSTALL: batch written to {bat_path}")

        # ── Étape 3 : Lancement batch + fermeture (80 → 100%) ───────────────
        _set_progress("installing", 85)

        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        _log("INSTALL: batch launched")

        _set_progress("launching", 100)

        # Petite pause pour que le JS puisse voir l'état "launching"
        import time as _time
        _time.sleep(1.0)

        _log("INSTALL: closing window")
        try:
            import webview
            if webview.windows:
                webview.windows[0].destroy()
        except Exception as e:
            _log(f"INSTALL: window.destroy() failed: {e}")

    except Exception as e:
        _log(f"INSTALL FATAL: {e}\n{traceback.format_exc()}")
        _set_progress("error", 0, str(e))
