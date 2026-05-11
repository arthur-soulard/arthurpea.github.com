"""
updater.py — Verifieur et installateur de mise a jour silencieux.

Lance un thread daemon qui interroge l'API GitHub Releases au demarrage.
Si une mise a jour est disponible, start_install() telecharge le Setup.exe,
lance un script batch qui attend la fermeture de l'app, installe et relance.
"""
from __future__ import annotations

import json
import os
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
        html_url = data.get("html_url", "")
        has_update = bool(latest) and _parse_ver(latest) > _parse_ver(current)

        # Trouve le Setup.exe dans les assets
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


def start_install() -> None:
    """
    Telecharge le Setup.exe, cree un script batch qui :
      1. attend 3s que l'app se ferme
      2. lance l'installation silencieuse
      3. relance l'app depuis le meme chemin
    Puis ferme l'app.
    """
    with _lock:
        download_url = _state.get("downloadUrl")

    if not download_url:
        raise RuntimeError("URL de telechargement introuvable")

    # Chemin de l'exe courant (fonctionne en mode compile PyInstaller)
    exe_path = sys.executable

    # Dossier temporaire de mise a jour
    tmp_dir = Path(tempfile.gettempdir()) / "suivi_pea_update"
    tmp_dir.mkdir(exist_ok=True)
    setup_path = tmp_dir / "Suivi_PEA_Setup.exe"

    # Telechargement
    req = urllib.request.Request(
        download_url,
        headers={"User-Agent": "Suivi-PEA-Updater/2"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        setup_path.write_bytes(r.read())

    # Script batch : force-kill l'exe -> installe -> relance
    bat_path = tmp_dir / "update.bat"
    bat_path.write_text(
        f'@echo off\n'
        f'timeout /t 2 /nobreak > nul\n'
        f'taskkill /F /IM Suivi_PEA.exe /T > nul 2>&1\n'
        f'timeout /t 2 /nobreak > nul\n'
        f'"{setup_path}" /VERYSILENT /NORESTART\n'
        f'timeout /t 5 /nobreak > nul\n'
        f'start "" "{exe_path}"\n'
        f'(goto) 2>nul & del "%~f0"\n',
        encoding="utf-8",
    )

    # Lance le batch en arriere-plan (fenetres cachees)
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # Ferme l'app
    try:
        import webview
        webview.windows[0].destroy()
    except Exception:
        pass
