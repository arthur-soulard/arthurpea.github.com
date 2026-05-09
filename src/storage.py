"""
storage.py — Gestion du stockage JSON pour Suivi PEA.

Toutes les donnees vivent dans :
    %APPDATA%\\Suivi PEA\\pea_data.json

Avec une rotation de backups quotidiens (7 derniers jours) dans :
    %APPDATA%\\Suivi PEA\\backups\\pea_data_YYYY-MM-DD.json

Ecriture atomique : on ecrit dans un .tmp puis on renomme, pour ne jamais
corrompre le fichier en cas de coupure.
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import datetime
import tempfile
from pathlib import Path
from typing import Optional, Tuple


APP_NAME = "Suivi PEA"
DATA_FILE = "pea_data.json"
BACKUP_DIR = "backups"
BACKUP_KEEP_DAYS = 7


# ─── Localisation du dossier de l'app ─────────────────────────────────────────

def _exe_dir() -> Path:
    """Dossier ou se trouve le .exe (ou le script .py en mode dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent  # remonte de src/ vers la racine


def get_app_dir() -> Path:
    """
    Retourne le dossier racine de donnees (Donnees/ a cote de l'exe).
    """
    base = _exe_dir() / "Donnees"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        if sys.platform == "win32":
            fallback = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            fallback = Path.home() / ".local" / "share"
        fallback = fallback / APP_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


# ─── Multi-profils (multi-PEA) ────────────────────────────────────────────
PROFILES_FILE = "profiles.json"   # liste profils + actif


def _profiles_path() -> Path:
    return get_app_dir() / PROFILES_FILE


def get_profiles_state() -> dict:
    """Retourne {active: 'default', profiles: [{slug, label}]}."""
    p = _profiles_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if "active" in d and "profiles" in d:
                return d
        except Exception:
            pass
    # Default initial
    state = {
        "active": "default",
        "profiles": [{"slug": "default", "label": "Mon PEA"}],
    }
    save_profiles_state(state)
    return state


def save_profiles_state(state: dict) -> None:
    p = _profiles_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_profile_dir(slug: str = None) -> Path:
    """Dossier dedie a un profil (data + backups)."""
    if slug is None:
        slug = get_profiles_state()["active"]
    pdir = get_app_dir() / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    return pdir


# ─── Recuperation : scan d'anciens dossiers Donnees ────────────────────────
def scan_orphan_data() -> list:
    """
    Cherche d'anciens fichiers pea_data.json sur le PC (cas : exe deplace
    sans son dossier Donnees). Retourne une liste de candidats tries du
    plus interessant au moins.
    """
    home = Path.home()
    candidates = []

    # Emplacements typiques a scanner (en surface, on ne descend pas profond)
    spots = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "AppData" / "Local" / "Programs" / "Suivi PEA",
        home / "AppData" / "Roaming" / "Suivi PEA",
    ]

    # Patterns a chercher dans chaque spot (max 3 niveaux de profondeur)
    seen = set()
    current_data_path = get_data_path().resolve()

    for spot in spots:
        if not spot.exists():
            continue
        try:
            for found in spot.rglob(DATA_FILE):
                resolved = found.resolve()
                if resolved == current_data_path:
                    continue  # ignorer le fichier courant
                if resolved in seen:
                    continue
                seen.add(resolved)
                # Limite la profondeur
                rel_parts = found.relative_to(spot).parts
                if len(rel_parts) > 5:
                    continue
                try:
                    sz = found.stat().st_size
                    if sz < 500:
                        continue  # probablement vide
                    mtime = found.stat().st_mtime
                    # Lit pour compter positions/tx
                    with open(found, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    positions = len(d.get("positions") or [])
                    txs       = len(d.get("transactions") or [])
                    deps      = len(d.get("depots") or [])
                    if positions == 0 and txs == 0 and deps == 0:
                        continue  # vraiment vide, pas interessant
                    candidates.append({
                        "path":         str(found),
                        "size":         sz,
                        "mtime":        int(mtime),
                        "positions":    positions,
                        "transactions": txs,
                        "depots":       deps,
                        "prenom":       (d.get("config") or {}).get("prenom") or "",
                    })
                except Exception:
                    continue
        except Exception:
            continue

    # Trie : plus de positions d'abord, puis plus recent
    candidates.sort(key=lambda c: (-c["positions"] - c["transactions"], -c["mtime"]))
    return candidates[:5]


def recover_from(source_path: str) -> dict:
    """Copie pea_data.json source vers l'emplacement actif. Retourne stats."""
    src = Path(source_path)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Source introuvable : {source_path}")
    dst = get_data_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Lit + verifie le JSON avant de copier
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Sauvegarde l'ancien fichier au cas ou
    if dst.exists():
        backup = dst.parent / (dst.stem + ".pre-recovery.json")
        try:
            import shutil
            shutil.copy2(dst, backup)
        except Exception:
            pass
    save_data(data)
    return {
        "positions":    len(data.get("positions") or []),
        "transactions": len(data.get("transactions") or []),
        "depots":       len(data.get("depots") or []),
    }


def get_data_path() -> Path:
    """Chemin du fichier pea_data.json pour le profil actif."""
    # Compatibilite : si l'ancien fichier existe a la racine ET aucun profil
    # personnalise, on continue d'utiliser cet emplacement (ou on migre).
    legacy = get_app_dir() / DATA_FILE
    state = get_profiles_state()
    if state["active"] == "default":
        new_path = get_profile_dir("default") / DATA_FILE
        # Migration : si le legacy existe et que le nouveau n'existe pas, on bouge
        if legacy.exists() and not new_path.exists():
            try:
                import shutil
                shutil.copy2(legacy, new_path)
            except Exception:
                pass
        # On continue a utiliser legacy si lui seul existe (zero-disruption)
        if legacy.exists() and not new_path.exists():
            return legacy
        return new_path
    return get_profile_dir(state["active"]) / DATA_FILE


def get_backup_dir() -> Path:
    """Dossier backups pour le profil actif."""
    state = get_profiles_state()
    if state["active"] == "default":
        # Compat : utilise le backups racine si un fichier legacy existe
        legacy_back = get_app_dir() / BACKUP_DIR
        if (get_app_dir() / DATA_FILE).exists() and legacy_back.exists():
            return legacy_back
    return get_profile_dir(state["active"]) / BACKUP_DIR


def get_log_path() -> Path:
    return get_app_dir() / "crash.log"


# ─── Donnees par defaut (pour un nouvel utilisateur) ──────────────────────────

def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "app": APP_NAME,
            "createdAt": datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
            "schema": "pea_data.v1",
        },
        "config": {
            "prenom": "",
            "banque": "",
            "ouverture": "",
        },
        "positions": [],
        "transactions": [],
        "depots": [],
        "divReceived": [],
        "divFuture": [],
        "wishlist": [],
        "strategies": [],
        "closedPositions": [],
        "cashSolde": 0,
        "_nid": {"pos": 1, "tx": 1, "wish": 1, "dep": 1, "div": 1, "divf": 1, "rule": 1},
        # Cache des cours et historiques (pour le mode hors-ligne)
        "_cache": {
            "prices": {},   # {ticker: {prix, w1, m1, y1, ts}}
            "history": {},  # {ticker: {dates: [...], closes: [...], ts}}
            "lastFetch": None,
        },
        # Preferences UI
        "ui": {
            "theme": "light",         # light | dark | auto
            "windowSize": [1280, 800],
            "windowPos": None,        # [x, y] ou None pour centrer
            "lastTab": "pos",
        },
        # Preferences notifications
        "notifs": {
            "bigMove": True,          # cours >+5% ou <-5%
            "dividend": True,         # dividende prevu aujourd'hui
            "yahooDown": True,        # Yahoo injoignable
        },
    }


# ─── Lecture / ecriture ───────────────────────────────────────────────────────

# Variable globale qui stocke l'origine du dernier load_data (pour le diag)
_LAST_LOAD_INFO = {"source": "?", "error": None}


def get_last_load_info() -> dict:
    return dict(_LAST_LOAD_INFO)


def load_data() -> dict:
    """
    Charge les donnees.
    IMPORTANT : ne JAMAIS ecrire dans pea_data.json depuis cette fonction —
    sinon une lecture qui echoue peut detruire les donnees existantes.
    On retourne juste default_data() en memoire si la lecture casse.
    """
    path = get_data_path()
    _LAST_LOAD_INFO["source"] = "?"
    _LAST_LOAD_INFO["error"]  = None

    exists = path.exists()
    _LAST_LOAD_INFO["exists_check"] = exists

    # 1. Tente la lecture du fichier principal
    if exists:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = default_data()
            for k, v in data.items():
                merged[k] = v
            for sub in ("ui", "notifs", "_cache", "_meta"):
                if sub in merged and isinstance(merged[sub], dict):
                    base = default_data()[sub]
                    for k, v in base.items():
                        merged[sub].setdefault(k, v)
            _LAST_LOAD_INFO["source"] = "main_file"
            return merged
        except Exception as e:
            _LAST_LOAD_INFO["error"] = f"main: {type(e).__name__}: {e}"
            print(f"[storage] lecture pea_data.json KO: {e}", flush=True)
    else:
        _LAST_LOAD_INFO["error"] = "main: file does not exist"

    # 2. Si echec, tente le backup le plus recent
    backup = _latest_backup()
    if backup and backup.exists():
        try:
            with open(backup, "r", encoding="utf-8") as f:
                data = json.load(f)
            _LAST_LOAD_INFO["source"] = "backup:" + backup.name
            return data
        except Exception as e:
            _LAST_LOAD_INFO["error"] = (_LAST_LOAD_INFO["error"] or "") + f" | backup: {e}"

    # 3. Fallback memoire SEULEMENT
    _LAST_LOAD_INFO["source"] = "default_fallback"
    return default_data()


def save_data(data: dict) -> None:
    """Ecrit le fichier de maniere atomique + backup quotidien."""
    path = get_data_path()
    data.setdefault("_meta", {})
    data["_meta"]["lastSavedAt"] = datetime.datetime.now().isoformat(timespec="seconds")

    # Ecriture atomique : tmp -> rename
    fd, tmp_path = tempfile.mkstemp(prefix=".pea_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise

    _daily_backup(data)


def _daily_backup(data: dict) -> None:
    """Cree (ou met a jour) le backup du jour, et supprime les > 7 jours."""
    today = datetime.date.today().isoformat()
    backup_dir = get_backup_dir()
    backup_path = backup_dir / f"pea_data_{today}.json"
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[storage] Backup quotidien impossible : {e}", flush=True)
        return

    # Rotation : on ne garde que les BACKUP_KEEP_DAYS plus recents
    backups = sorted(backup_dir.glob("pea_data_*.json"))
    while len(backups) > BACKUP_KEEP_DAYS:
        old = backups.pop(0)
        try:
            old.unlink()
        except Exception:
            pass


def _latest_backup() -> Optional[Path]:
    backups = sorted(get_backup_dir().glob("pea_data_*.json"))
    return backups[-1] if backups else None


# ─── Export / import (boutons dans l'UI) ──────────────────────────────────────

def export_to(target_path: str) -> bool:
    """Copie le pea_data.json vers le chemin choisi par l'utilisateur."""
    src = get_data_path()
    if not src.exists():
        return False
    try:
        shutil.copyfile(src, target_path)
        return True
    except Exception as e:
        print(f"[storage] Export echoue : {e}", flush=True)
        return False


def import_from(source_path: str) -> Tuple[bool, str]:
    """
    Importe un fichier JSON externe :
      1. Valide qu'il est lisible et a une structure plausible
      2. Sauvegarde l'actuel en backup_YYYYMMDD-HHMMSS_avant_import.json
      3. Le remplace
    Retourne (ok, message).
    """
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            new_data = json.load(f)
    except Exception as e:
        return False, f"Fichier illisible : {e}"

    # Validation minimale
    required = ("positions", "transactions", "depots")
    for k in required:
        if k not in new_data:
            return False, f"Fichier invalide : champ '{k}' manquant."

    # Backup de securite avant ecrasement
    if get_data_path().exists():
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = get_backup_dir() / f"pea_data_avant_import_{ts}.json"
        try:
            shutil.copyfile(get_data_path(), safe)
        except Exception:
            pass

    save_data(new_data)
    return True, "Donnees importees avec succes."


# ─── Migration depuis l'ancien tracker (localStorage Brave) ───────────────────

def import_from_legacy(payload: dict) -> Tuple[bool, str]:
    """
    Recoit le contenu du localStorage de l'ancien tracker (cles pea4_v4*),
    et le convertit au format pea_data.v1.
    """
    try:
        raw = payload.get("pea4_v4")
        if not raw:
            return False, "Cle 'pea4_v4' introuvable dans la sauvegarde."
        old = json.loads(raw) if isinstance(raw, str) else raw

        new_data = default_data()
        new_data["config"] = {
            "prenom":    old.get("prenom", ""),
            "banque":    old.get("banque", ""),
            "ouverture": old.get("ouverture", ""),
        }
        new_data["positions"]       = old.get("positions", [])
        new_data["transactions"]    = old.get("transactions", [])
        new_data["depots"]          = old.get("depots", [])
        new_data["divReceived"]     = old.get("divReceived", [])
        new_data["divFuture"]       = old.get("divFuture", [])
        new_data["wishlist"]        = old.get("wishlist", [])
        new_data["strategies"]      = old.get("strategies", [])
        new_data["closedPositions"] = old.get("closedPositions", [])
        new_data["cashSolde"]       = old.get("cashSolde", 0)
        new_data["_nid"]            = old.get("_nid", new_data["_nid"])

        # On ramene aussi le cache historique si dispo (gain de temps au lancement)
        hist_raw = payload.get("pea4_v4_hist")
        if hist_raw:
            try:
                hist = json.loads(hist_raw) if isinstance(hist_raw, str) else hist_raw
                new_data["_cache"]["history"] = hist.get("history", {})
            except Exception:
                pass

        var_raw = payload.get("pea4_v4_var")
        if var_raw:
            try:
                var = json.loads(var_raw) if isinstance(var_raw, str) else var_raw
                new_data["_cache"]["prices"] = var
            except Exception:
                pass

        save_data(new_data)
        return True, "Migration reussie."
    except Exception as e:
        return False, f"Erreur de migration : {e}"
