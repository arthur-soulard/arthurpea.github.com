"""
updater.py — Verifieur et installateur de mise a jour avec progression.

Lance un thread daemon qui interroge l'API GitHub Releases au demarrage.
start_install_async() telecharge en rapportant la progression (0-100%)
puis lance le batch et ferme l'app proprement.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import urllib.request
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ver(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


def _set_progress(step: str, pct: int, error: str | None = None) -> None:
    with _lock:
        _progress.update({"step": step, "pct": pct, "error": error})


# ── Check update ──────────────────────────────────────────────────────────────

def _fetch(current: str) -> None:
    try:
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
    except Exception:
        with _lock:
            _state["checked"] = True


def start_check(current_version: str) -> None:
    threading.Thread(target=_fetch, args=(current_version,), daemon=True).start()


def get_result() -> dict:
    with _lock:
        return dict(_state)


# ── Install with progress ─────────────────────────────────────────────────────

def get_progress() -> dict:
    with _lock:
        return dict(_progress)


def start_install_async() -> None:
    """Lance l'installation dans un thread — retourne immediatement."""
    threading.Thread(target=_do_install, daemon=True).start()


def _do_install() -> None:
    try:
        with _lock:
            download_url = _state.get("downloadUrl")

        if not download_url:
            _set_progress("error", 0, "URL de téléchargement introuvable")
            return

        exe_path = sys.executable
        tmp_dir = Path(tempfile.gettempdir()) / "suivi_pea_update"
        tmp_dir.mkdir(exist_ok=True)
        setup_path = tmp_dir / "Suivi_PEA_Setup.exe"

        # ── Étape 1 : Téléchargement (0 → 70%) ──────────────────────────────
        _set_progress("downloading", 0)
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "Suivi-PEA-Updater/2"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 65536  # 64 Ko
            with open(setup_path, "wb") as f:
                while True:
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 70)
                        _set_progress("downloading", pct)

        # ── Étape 2 : Préparation batch (70 → 80%) ───────────────────────────
        _set_progress("installing", 75)
        bat_path = tmp_dir / "update.bat"
        bat_path.write_text(
            f'@echo off\n'
            f':wait\n'
            f'tasklist /FI "IMAGENAME eq Suivi_PEA.exe" 2>nul | find /I "Suivi_PEA.exe" > nul\n'
            f'if not errorlevel 1 ( timeout /t 1 /nobreak > nul & goto wait )\n'
            f'"{setup_path}" /VERYSILENT /NORESTART\n'
            f'(goto) 2>nul & del "%~f0"\n',
            encoding="utf-8",
        )

        # ── Étape 3 : Lancement batch + fermeture (80 → 100%) ───────────────
        _set_progress("installing", 85)
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        _set_progress("launching", 100)

        # Ferme la fenetre proprement (le process s'arrete, PyInstaller nettoie)
        try:
            import webview
            webview.windows[0].destroy()
        except Exception:
            pass

    except Exception as e:
        _set_progress("error", 0, str(e))
