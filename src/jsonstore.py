"""
jsonstore.py — Socle commun de persistance JSON pour les modules annexes.

finances.py implemente deja ce schema (ecriture atomique .tmp -> rename,
backup quotidien, rotation 7 jours). Les modules ajoutes ensuite (sports.py,
pret.py) partagent la meme mecanique via cette petite classe, plutot que de
la recopier a chaque fois.

Depuis la v4.1.2, ces fichiers sont PROPRES a chaque utilisateur : ils vivent
dans <app_dir>/users/<slug>/ a cote de pea_data.json.
"""
from __future__ import annotations

import os
import json
import datetime
import tempfile
from pathlib import Path
from typing import Callable, Optional

import storage


BACKUP_KEEP_DAYS = 7


class JsonStore:
    """Un fichier JSON du dossier applicatif, avec backup quotidien."""

    def __init__(self, filename: str, backup_dirname: str, schema: str,
                 default_factory: Callable[[], dict], keep_days: int = BACKUP_KEEP_DAYS):
        self.filename       = filename
        self.backup_dirname = backup_dirname
        self.schema         = schema
        self.default_factory = default_factory
        self.keep_days      = keep_days
        # Prefixe des backups et des fichiers temporaires : "sports.json" -> "sports"
        self.stem = Path(filename).stem

    # ─── Chemins ──────────────────────────────────────────────────────────────

    def path(self) -> Path:
        return storage.get_user_dir() / self.filename

    def backup_dir(self) -> Path:
        d = storage.get_user_dir() / self.backup_dirname
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ─── Lecture ──────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Charge le fichier. Si absent ou illisible, retourne les defauts."""
        path = self.path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._merge_defaults(data)
            except Exception as e:
                print(f"[{self.stem}] lecture KO: {e}", flush=True)
                backup = self._latest_backup()
                if backup and backup.exists():
                    try:
                        with open(backup, "r", encoding="utf-8") as f:
                            return self._merge_defaults(json.load(f))
                    except Exception:
                        pass
        return self.default_factory()

    def _merge_defaults(self, data: dict) -> dict:
        """Conserve les valeurs sauvegardees, complete les cles manquantes."""
        merged = self.default_factory()
        for k, v in (data or {}).items():
            merged[k] = v
        for key in ("_meta", "_nid"):
            if isinstance(merged.get(key), dict):
                for k, v in self.default_factory().get(key, {}).items():
                    merged[key].setdefault(k, v)
        return merged

    # ─── Ecriture ─────────────────────────────────────────────────────────────

    def save(self, data: dict) -> None:
        """Ecriture atomique (.tmp -> rename) + backup quotidien."""
        path = self.path()
        data = data or {}
        data.setdefault("_meta", {})
        data["_meta"]["lastSavedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
        data["_meta"].setdefault("schema",    self.schema)
        data["_meta"].setdefault("version",   1)
        data["_meta"].setdefault("createdAt", datetime.date.today().isoformat())

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f".{self.stem}_", suffix=".tmp",
                                        dir=str(path.parent))
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

        self._daily_backup(data)

    # ─── Backups ──────────────────────────────────────────────────────────────

    def _daily_backup(self, data: dict) -> None:
        today = datetime.date.today().isoformat()
        backup_dir = self.backup_dir()
        try:
            with open(backup_dir / f"{self.stem}_{today}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[{self.stem}] backup quotidien KO: {e}", flush=True)
            return

        backups = sorted(backup_dir.glob(f"{self.stem}_*.json"))
        while len(backups) > self.keep_days:
            old = backups.pop(0)
            try:
                old.unlink()
            except Exception:
                pass

    def _latest_backup(self) -> Optional[Path]:
        try:
            backups = sorted(self.backup_dir().glob(f"{self.stem}_*.json"))
            return backups[-1] if backups else None
        except Exception:
            return None
