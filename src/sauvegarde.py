"""
sauvegarde.py — Sauvegarde externe du dossier Donnees vers une cle USB.

Principe
────────
Une sauvegarde = une archive .zip de TOUT le dossier Donnees (tous les
utilisateurs, users.json compris). C'est volontaire : une cle USB qu'on
rebranche apres un crash disque doit pouvoir remonter l'installation
entiere, pas un seul espace.

La configuration est donc, elle aussi, au niveau de l'installation :
<app_dir>/sauvegarde.json, a cote de users.json — et non dans le dossier
d'un utilisateur.

La lettre d'une cle USB change (E:, F:, G:...). On memorise donc le
NUMERO DE SERIE du volume, et on retrouve la cle quelle que soit la lettre
que Windows lui donne au prochain branchement.

Rien n'est chiffre : le zip est aussi lisible que les JSON d'origine.
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import zipfile
import datetime
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import storage


CONFIG_FILE = "sauvegarde.json"
ARCHIVE_PREFIX = "Pilote_"

# Dossiers du dossier Donnees qu'on ne sauvegarde pas : regenerables.
EXCLUDED_DIRS = {"icones"}

DRIVE_REMOVABLE = 2
DRIVE_FIXED     = 3


# ─── Configuration ────────────────────────────────────────────────────────────

def default_config() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "sauvegarde.v1",
            "createdAt": datetime.date.today().isoformat(),
        },
        # Destination
        "destination":    "",       # chemin complet, ex. "E:\\Sauvegardes Pilote"
        "volumeSerial":   "",       # numero de serie du volume (retrouve la cle)
        "volumeLabel":    "",       # nom affiche de la cle, pour l'UI
        "relativePath":   "",       # sous-dossier sur la cle, ex. "Sauvegardes Pilote"
        # Comportement
        "auto":           True,     # sauvegarder tout seul quand la cle est la
        "frequence":      "daily",  # daily | weekly | manual
        "keep":           10,       # nombre d'archives conservees (rotation)
        # Dernier resultat
        "lastBackupAt":   "",
        "lastBackupPath": "",
        "lastStatus":     "",       # ok | error | absent
        "lastError":      "",
        # Dernier televersement direct (bouton de l'accueil)
        "lastPushAt":     "",
        "lastPushPath":   "",
    }


def _config_path() -> Path:
    return storage.get_app_dir() / CONFIG_FILE


def load_config() -> dict:
    p = _config_path()
    cfg = default_config()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in (saved or {}).items():
                cfg[k] = v
        except Exception as e:
            print(f"[sauvegarde] config illisible : {e}", flush=True)
    return cfg


def save_config(cfg: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sauvegarde_", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


# ─── Detection des volumes amovibles (Windows) ────────────────────────────────

def _volume_info(root: str) -> dict:
    """Nom, numero de serie et systeme de fichiers d'un volume ("E:\\")."""
    info = {"label": "", "serial": "", "fs": ""}
    if sys.platform != "win32":
        return info
    try:
        import ctypes
        name_buf   = ctypes.create_unicode_buffer(261)
        fs_buf     = ctypes.create_unicode_buffer(261)
        serial     = ctypes.c_ulong(0)
        max_comp   = ctypes.c_ulong(0)
        flags      = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            name_buf, ctypes.sizeof(name_buf),
            ctypes.byref(serial), ctypes.byref(max_comp), ctypes.byref(flags),
            fs_buf, ctypes.sizeof(fs_buf),
        )
        if ok:
            info["label"]  = name_buf.value or ""
            info["fs"]     = fs_buf.value or ""
            # Certaines cles (FAT32 bas de gamme, cartes SD) rendent un numero
            # de serie nul : il n'identifie alors rien du tout. On le traite
            # comme absent plutot que de croire reconnaitre la bonne cle.
            info["serial"] = "" if serial.value == 0 else f"{serial.value:08X}"
    except Exception:
        pass
    return info


def _disk_space(root: str) -> Tuple[int, int]:
    """(libre, total) en octets, (0, 0) si indisponible."""
    try:
        usage = shutil.disk_usage(root)
        return usage.free, usage.total
    except Exception:
        return 0, 0


def list_removable_drives() -> list:
    """Cles USB et disques externes actuellement branches."""
    drives = []
    if sys.platform != "win32":
        return drives
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        return drives

    for i in range(26):
        if not (mask >> i) & 1:
            continue
        root = f"{chr(65 + i)}:\\"
        try:
            dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        except Exception:
            continue
        if dtype != DRIVE_REMOVABLE:
            continue
        info = _volume_info(root)
        free, total = _disk_space(root)
        if not total:
            continue  # lecteur declare mais sans media (lecteur de carte vide)
        drives.append({
            "root":   root,
            "letter": root[:2],
            "label":  info["label"] or "Volume amovible",
            "serial": info["serial"],
            "fs":     info["fs"],
            "free":   free,
            "total":  total,
        })
    return drives


def _find_drive_by_serial(serial: str) -> Optional[str]:
    """Retrouve la racine ("E:\\") du volume portant ce numero de serie."""
    if not serial:
        return None
    for d in list_removable_drives():
        if d["serial"] and d["serial"] == serial:
            return d["root"]
    return None


# ─── Resolution de la destination ─────────────────────────────────────────────

def resolve_destination(cfg: dict = None) -> dict:
    """
    Ou ecrire, maintenant ?

    Retourne {ready, path, reason, drive}. La cle est cherchee par numero de
    serie en priorite : si Windows lui a donne une autre lettre depuis la
    derniere fois, on la suit.
    """
    cfg = cfg or load_config()
    dest = (cfg.get("destination") or "").strip()
    serial = (cfg.get("volumeSerial") or "").strip()
    rel = (cfg.get("relativePath") or "").strip().strip("\\/")

    if not dest and not serial:
        return {"ready": False, "path": "", "reason": "unset",
                "message": "Aucune destination choisie.", "drive": None}

    # 1. Par numero de serie — resiste au changement de lettre
    if serial:
        root = _find_drive_by_serial(serial)
        if root:
            path = Path(root) / rel if rel else Path(root)
            return {"ready": True, "path": str(path), "reason": "ok",
                    "message": "", "drive": root[:2]}
        # La cle memorisee n'est pas branchee : on ne se rabat PAS sur le
        # chemin brut, il pointerait sur une autre cle qui a herite la lettre.
        return {"ready": False, "path": dest, "reason": "absent",
                "message": f"La clé « {cfg.get('volumeLabel') or 'de sauvegarde'} » "
                           f"n'est pas branchée.",
                "drive": None}

    # 2. Pas de numero de serie utilisable : on suit le NOM de volume, qui
    #    reste un indice correct, et a defaut le chemin brut.
    label = (cfg.get("volumeLabel") or "").strip()
    if label:
        for d in list_removable_drives():
            if d["label"] and d["label"].lower() == label.lower():
                path = Path(d["root"]) / rel if rel else Path(d["root"])
                return {"ready": True, "path": str(path), "reason": "ok",
                        "message": "", "drive": d["letter"]}

    p = Path(dest)
    if p.exists():
        return {"ready": True, "path": str(p), "reason": "ok", "message": "", "drive": None}
    return {"ready": False, "path": dest, "reason": "absent",
            "message": (f"La clé « {label} » n'est pas branchée.") if label
                       else "Destination introuvable.",
            "drive": None}


def set_destination(path: str) -> dict:
    """
    Enregistre une destination choisie par l'utilisateur.

    Si le chemin est sur un volume amovible, on retient son numero de serie
    et le sous-dossier, de facon a retrouver la cle plus tard.
    """
    cfg = load_config()
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": f"Dossier inaccessible : {e}"}

    cfg["destination"]  = str(p)
    cfg["volumeSerial"] = ""
    cfg["volumeLabel"]  = ""
    cfg["relativePath"] = ""

    if sys.platform == "win32":
        try:
            root = os.path.splitdrive(str(p.resolve()))[0] + "\\"
            import ctypes
            dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
            if dtype == DRIVE_REMOVABLE:
                info = _volume_info(root)
                cfg["volumeSerial"] = info["serial"]       # "" si illisible
                cfg["volumeLabel"]  = info["label"] or ""
                rel = str(p.resolve())[len(root):]
                cfg["relativePath"] = rel.strip("\\/")
        except Exception:
            pass

    save_config(cfg)
    return {"ok": True, "config": cfg, "destination": resolve_destination(cfg)}


# ─── Fabrication de l'archive ─────────────────────────────────────────────────

def _iter_files(app_dir: Path):
    """Tous les fichiers a sauvegarder, en ignorant le regenerable."""
    for root, dirs, files in os.walk(app_dir):
        rel_root = Path(root).relative_to(app_dir)
        # Elague les dossiers exclus (comparaison sur le premier segment)
        dirs[:] = [d for d in dirs
                   if not (rel_root == Path(".") and d in EXCLUDED_DIRS)]
        for name in files:
            if name.endswith(".tmp") or name.startswith(".sauvegarde_"):
                continue
            full = Path(root) / name
            yield full, str(rel_root / name) if str(rel_root) != "." else name


def _archive_name() -> str:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M")
    return f"{ARCHIVE_PREFIX}{stamp}.zip"


def run_backup(reason: str = "manuel") -> dict:
    """Ecrit une archive dans la destination, puis applique la rotation."""
    cfg  = load_config()
    dest = resolve_destination(cfg)

    if not dest["ready"]:
        cfg["lastStatus"] = "absent"
        cfg["lastError"]  = dest["message"]
        save_config(cfg)
        return {"ok": False, "reason": dest["reason"], "error": dest["message"]}

    app_dir = storage.get_app_dir()
    out_dir = Path(dest["path"])
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "reason": "error", "error": f"Dossier inaccessible : {e}"}

    target = out_dir / _archive_name()
    # On ecrit d'abord a cote, puis on renomme : une cle debranchee en plein
    # milieu ne laisse pas une archive tronquee portant un nom valide.
    tmp_target = out_dir / (target.name + ".part")

    count = 0
    try:
        with zipfile.ZipFile(tmp_target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for full, arc in _iter_files(app_dir):
                try:
                    z.write(full, arcname=str(Path("Donnees") / arc))
                    count += 1
                except Exception as e:
                    print(f"[sauvegarde] fichier ignore {full}: {e}", flush=True)
            z.writestr("Donnees/_sauvegarde.txt", _manifest(count, reason))
        os.replace(tmp_target, target)
    except Exception as e:
        for leftover in (tmp_target,):
            try:
                leftover.unlink()
            except Exception:
                pass
        cfg["lastStatus"] = "error"
        cfg["lastError"]  = str(e)
        save_config(cfg)
        return {"ok": False, "reason": "error", "error": str(e)}

    size = target.stat().st_size
    removed = _rotate(out_dir, int(cfg.get("keep") or 10))

    cfg["lastBackupAt"]   = datetime.datetime.now().isoformat(timespec="seconds")
    cfg["lastBackupPath"] = str(target)
    cfg["lastStatus"]     = "ok"
    cfg["lastError"]      = ""
    save_config(cfg)

    return {"ok": True, "path": str(target), "files": count,
            "size": size, "removed": removed, "reason": reason}


def _manifest(count: int, reason: str) -> str:
    users = storage.get_users_state()
    lignes = [
        "Sauvegarde Pilote",
        f"Date       : {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Origine    : {storage.get_app_dir()}",
        f"Fichiers   : {count}",
        f"Declencheur: {reason}",
        f"Utilisateurs : " + ", ".join(u.get("label", u.get("slug", "?"))
                                       for u in users.get("users", [])),
        "",
        "Pour restaurer : Pilote > Parametres > Sauvegarde > Restaurer,",
        "ou decompresser ce zip par-dessus le dossier Donnees, app fermee.",
    ]
    return "\n".join(lignes)


def _rotate(out_dir: Path, keep: int) -> int:
    """Ne garde que les `keep` archives les plus recentes."""
    if keep <= 0:
        return 0
    try:
        archives = sorted(out_dir.glob(f"{ARCHIVE_PREFIX}*.zip"))
    except Exception:
        return 0
    removed = 0
    while len(archives) > keep:
        old = archives.pop(0)
        try:
            old.unlink()
            removed += 1
        except Exception:
            pass
    return removed


# ─── Televersement direct (bouton de l'accueil) ───────────────────────────────
# Different des archives : ici on ecrit un MIROIR du dossier Donnees dans
# <cle>/Pilote/Donnees. Pas d'historique, pas de rotation — on ecrase, c'est
# une actualisation. Les deux mecanismes coexistent : le miroir pour recuperer
# ses fichiers tout de suite, les archives pour pouvoir remonter dans le temps.

MIRROR_DIR = os.path.join("Pilote", "Donnees")


def push_to_usb(root: str = None) -> dict:
    """
    Copie tout le dossier Donnees vers <cle>/Pilote/Donnees, en ecrasant.

    Sans `root`, la cle est choisie automatiquement s'il n'y en a qu'une ;
    s'il y en a plusieurs, on rend la liste pour que l'UI demande laquelle.
    """
    drives = list_removable_drives()
    if not drives:
        return {"ok": False, "reason": "no_drive",
                "error": "Aucune clé USB détectée. Branche-la puis réessaie."}

    if root:
        chosen = next((d for d in drives if d["root"].lower() == root.lower()), None)
        if not chosen:
            return {"ok": False, "reason": "no_drive",
                    "error": "Cette clé n'est plus branchée."}
    elif len(drives) == 1:
        chosen = drives[0]
    else:
        # Si une cle est deja configuree pour les archives, on la privilegie
        cfg = load_config()
        chosen = next((d for d in drives
                       if d["serial"] and d["serial"] == cfg.get("volumeSerial")), None)
        if not chosen:
            return {"ok": False, "reason": "choose", "drives": drives,
                    "error": "Plusieurs clés sont branchées."}

    app_dir = storage.get_app_dir()
    dest = Path(chosen["root"]) / MIRROR_DIR
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "reason": "error",
                "error": f"Écriture impossible sur {chosen['letter']} : {e}"}

    copies, octets, echecs = 0, 0, []
    for full, rel in _iter_files(app_dir):
        target = dest / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # copy2 preserve la date : un fichier inchange reste identique
            shutil.copy2(full, target)
            copies += 1
            octets += target.stat().st_size
        except Exception as e:
            echecs.append(f"{rel} ({e})")

    try:
        (dest / "_sauvegarde.txt").write_text(_manifest(copies, "téléversement"),
                                              encoding="utf-8")
    except Exception:
        pass

    cfg = load_config()
    cfg["lastPushAt"]   = datetime.datetime.now().isoformat(timespec="seconds")
    cfg["lastPushPath"] = str(dest)
    try:
        save_config(cfg)
    except Exception:
        pass

    return {"ok": True, "path": str(dest), "files": copies, "size": octets,
            "drive": chosen["letter"], "label": chosen["label"],
            "failed": echecs[:5], "failedCount": len(echecs)}


def usb_state() -> dict:
    """Etat rapide pour l'accueil : y a-t-il une cle, et de quand date l'envoi ?"""
    cfg = load_config()
    drives = list_removable_drives()
    return {"ok": True, "drives": drives, "count": len(drives),
            "lastPushAt": cfg.get("lastPushAt", ""),
            "lastPushPath": cfg.get("lastPushPath", "")}


# ─── Inventaire ───────────────────────────────────────────────────────────────

def list_backups() -> dict:
    """Archives presentes dans la destination, la plus recente en tete."""
    dest = resolve_destination()
    if not dest["ready"]:
        return {"ok": False, "reason": dest["reason"], "error": dest["message"],
                "backups": []}
    out = []
    try:
        for p in sorted(Path(dest["path"]).glob(f"{ARCHIVE_PREFIX}*.zip"), reverse=True):
            try:
                st = p.stat()
                out.append({
                    "name": p.name,
                    "path": str(p),
                    "size": st.st_size,
                    "date": datetime.datetime.fromtimestamp(st.st_mtime)
                                    .isoformat(timespec="seconds"),
                })
            except Exception:
                pass
    except Exception as e:
        return {"ok": False, "reason": "error", "error": str(e), "backups": []}
    free, total = _disk_space(dest["path"])
    return {"ok": True, "backups": out, "path": dest["path"],
            "free": free, "total": total}


# ─── Sauvegarde automatique ───────────────────────────────────────────────────

def is_due(cfg: dict = None) -> bool:
    """La sauvegarde automatique doit-elle tourner maintenant ?"""
    cfg = cfg or load_config()
    if not cfg.get("auto"):
        return False
    freq = cfg.get("frequence") or "daily"
    if freq == "manual":
        return False
    last = cfg.get("lastBackupAt") or ""
    if not last:
        return True
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except Exception:
        return True
    delta = datetime.datetime.now() - last_dt
    return delta >= (datetime.timedelta(days=7) if freq == "weekly"
                     else datetime.timedelta(days=1))


def auto_backup_if_due() -> dict:
    """
    Appelee au demarrage. Silencieuse : si la cle n'est pas la, on ne
    derange pas l'utilisateur, on note juste le statut.
    """
    cfg = load_config()
    if not is_due(cfg):
        return {"ok": False, "reason": "not_due"}
    dest = resolve_destination(cfg)
    if not dest["ready"]:
        cfg["lastStatus"] = "absent"
        cfg["lastError"]  = dest["message"]
        save_config(cfg)
        return {"ok": False, "reason": dest["reason"]}
    return run_backup(reason="automatique")


# ─── Restauration ─────────────────────────────────────────────────────────────

def restore_from(zip_path: str) -> dict:
    """
    Restaure une archive par-dessus le dossier Donnees.

    Deux garde-fous :
      * l'archive est validee avant d'ecrire quoi que ce soit ;
      * une archive de securite de l'etat ACTUEL est ecrite a cote, pour
        pouvoir revenir en arriere si la restauration ne donne pas ce qu'on
        attendait.

    On ecrase fichier par fichier, sans vider le dossier au prealable : une
    archive incomplete ne doit jamais faire disparaitre un utilisateur qui
    n'y figure pas.
    """
    src = Path(zip_path)
    if not src.exists():
        return {"ok": False, "error": "Archive introuvable."}

    try:
        with zipfile.ZipFile(src) as z:
            bad = z.testzip()
            if bad:
                return {"ok": False, "error": f"Archive corrompue ({bad})."}
            members = [m for m in z.namelist() if m.startswith("Donnees/")]
            if not members:
                return {"ok": False,
                        "error": "Ce zip n'est pas une sauvegarde Pilote."}
    except zipfile.BadZipFile:
        return {"ok": False, "error": "Fichier illisible (zip invalide)."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    app_dir = storage.get_app_dir()

    # Filet de securite : l'etat actuel, avant d'ecraser
    safety = ""
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M%S")
        safety_path = app_dir.parent / f"Pilote_avant-restauration_{stamp}.zip"
        with zipfile.ZipFile(safety_path, "w", zipfile.ZIP_DEFLATED) as z:
            for full, arc in _iter_files(app_dir):
                try:
                    z.write(full, arcname=str(Path("Donnees") / arc))
                except Exception:
                    pass
        safety = str(safety_path)
    except Exception as e:
        print(f"[sauvegarde] archive de securite KO : {e}", flush=True)

    written = 0
    try:
        with zipfile.ZipFile(src) as z:
            for member in members:
                if member.endswith("/"):
                    continue
                rel = member[len("Donnees/"):]
                # Le manifeste est documentaire ; la config de sauvegarde
                # decrit la cle ACTUELLE et ne doit pas revenir en arriere
                # (sinon restaurer une vieille archive repointerait vers une
                # cle qu'on n'utilise peut-etre plus).
                if not rel or rel in ("_sauvegarde.txt", CONFIG_FILE):
                    continue
                # Refuse toute sortie du dossier (zip slip). Comparaison par
                # ancetres et non par prefixe de chaine : un dossier voisin
                # nomme "DonneesX" passait le test startswith et laissait une
                # archive piegee ecrire en dehors de Donnees/.
                app_r  = app_dir.resolve()
                target = (app_dir / rel).resolve()
                if app_r not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as fsrc, open(target, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
                written += 1
    except Exception as e:
        return {"ok": False, "error": str(e), "safety": safety}

    return {"ok": True, "files": written, "safety": safety,
            "path": str(app_dir)}


# ─── Etat complet pour l'UI ───────────────────────────────────────────────────

def status() -> dict:
    """Tout ce dont l'ecran Parametres a besoin, en un appel."""
    cfg  = load_config()
    dest = resolve_destination(cfg)
    return {
        "ok": True,
        "config":      cfg,
        "destination": dest,
        "drives":      list_removable_drives(),
        "due":         is_due(cfg),
        "appDir":      str(storage.get_app_dir()),
    }
