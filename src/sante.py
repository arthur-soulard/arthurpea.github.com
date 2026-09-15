"""
sante.py — Module "Sante" : pesees issues de la balance connectee (app FitDays).

Deux facons d'entrer une mesure :
  * en deposant les captures d'ecran FitDays -> lecture automatique (OCR) ;
  * a la main, si l'OCR se trompe ou si on n'a pas de capture.

OCR
───
Le moteur est celui integre a Windows (Windows.Media.Ocr), pilote par
`ocr_win.ps1`. Aucune dependance nouvelle, aucun binaire embarque, aucun acces
reseau : les captures ne quittent jamais le PC.

Le moteur ne voit pas tout du premier coup — le texte colore de FitDays (vert,
orange, rouge, bleu) lui echappe souvent. On lance donc PLUSIEURS passes avec
des pretraitements differents (niveaux de gris, binarisation, echelles) et on
fusionne : chaque passe rattrape ce que les autres ratent.

L'appariement libelle -> valeur se fait par POSITION, jamais par ordre de
lecture : la mise en page est en deux colonnes, le moteur restitue les lignes
dans un ordre imprevisible, et FitDays coupe ses libelles longs sur deux
lignes en intercalant la valeur entre les deux (voir _extract_values).

Emplacement : <app_dir>/users/<slug>/sante.json
Backup quotidien : <app_dir>/users/<slug>/backups_sante/sante_YYYY-MM-DD.json

Modele de donnees
─────────────────
mesures : {id, date:"YYYY-MM-DD", time:"HH:MM", source:"ocr"|"manuel",
           note:"", + une cle par metrique (voir METRICS)}
goals   : {id, metric:"poids", target:75.0, start:79.6, date:"YYYY-MM-DD"|"",
           status:"active|done|archived", createdAt, doneAt, note}
profil  : {taille_cm, sexe, naissance}
"""
from __future__ import annotations

import os
import re
import sys
import json
import shutil
import datetime
import tempfile
import subprocess
import unicodedata
from pathlib import Path
from typing import Optional

import jsonstore


# ─── Catalogue des metriques ──────────────────────────────────────────────────
# "aliases" : ce que l'OCR peut renvoyer pour ce libelle, en minuscules et sans
# accents (voir _norm). On matche par prefixe/inclusion, donc pas besoin d'etre
# exhaustif sur les fins de mots.

METRICS = [
    {"id": "poids",               "label": "Poids",                 "unit": "kg",
     "aliases": ["poids"], "decimals": 1, "key": True, "range": [25, 300]},
    {"id": "imc",                 "label": "IMC",                   "unit": "",
     "aliases": ["imc", "bmi"], "decimals": 1, "range": [8, 70]},
    {"id": "graisse",             "label": "Graisse corporelle",    "unit": "%",
     "aliases": ["graisse corporelle"], "decimals": 1, "key": True, "range": [2, 70]},
    {"id": "taux_musculaire",     "label": "Taux musculaire",       "unit": "%",
     "aliases": ["taux musculaire"], "decimals": 1, "range": [15, 100]},
    {"id": "poids_sans_graisse",  "label": "Poids sans graisse",    "unit": "kg",
     "aliases": ["poids sans graisse"], "decimals": 1, "range": [15, 250]},
    {"id": "graisse_sous_cutanee", "label": "Graisse sous-cutanée", "unit": "%",
     "aliases": ["graisse sous-cutanee", "graisse sous cutanee"], "decimals": 1,
     "range": [1, 60]},
    {"id": "graisse_viscerale",   "label": "Graisse viscérale",     "unit": "",
     "aliases": ["graisse viscerale"], "decimals": 1, "range": [1, 40]},
    {"id": "eau",                 "label": "Eau corporelle",        "unit": "%",
     "aliases": ["eau corporelle"], "decimals": 1, "range": [20, 85]},
    {"id": "muscle_squelettique", "label": "Muscle squelettique",   "unit": "%",
     "aliases": ["muscle squelettique"], "decimals": 1, "range": [10, 80]},
    {"id": "masse_musculaire",    "label": "Masse musculaire",      "unit": "kg",
     "aliases": ["masse musculaire"], "decimals": 1, "key": True, "range": [10, 200]},
    {"id": "masse_osseuse",       "label": "Masse osseuse",         "unit": "kg",
     "aliases": ["masse osseuse"], "decimals": 1, "range": [0.5, 12]},
    {"id": "proteine",            "label": "Protéine",              "unit": "%",
     "aliases": ["proteine"], "decimals": 1, "range": [3, 45]},
    {"id": "metabolisme",         "label": "Métabolisme de base",   "unit": "kcal",
     "aliases": ["taux metabolique basal", "metabolique basal", "metabolisme"],
     "decimals": 0, "range": [500, 6000]},
    {"id": "age_corporel",        "label": "Âge corporel",          "unit": "",
     "aliases": ["age corporel"], "decimals": 0, "range": [5, 120]},
]

METRIC_IDS = [m["id"] for m in METRICS]
_BY_ID = {m["id"]: m for m in METRICS}


def metric(mid: str) -> dict:
    return _BY_ID.get(mid, {})


# ─── Stockage ─────────────────────────────────────────────────────────────────

def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "sante.v1",
            "createdAt":   datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "mesures": [],
        "goals":   [],
        "profil":  {"taille_cm": None, "sexe": "", "naissance": ""},
        "_nid":    {"mesure": 1, "goal": 1},
    }


_store = jsonstore.JsonStore(
    filename="sante.json",
    backup_dirname="backups_sante",
    schema="sante.v1",
    default_factory=default_data,
)


def get_sante_path():
    return _store.path()


def load_data() -> dict:
    return _store.load()


def save_data(data: dict) -> None:
    _store.save(data)


# ─── Outils texte ─────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Minuscules, sans accents, espaces normalises : pour comparer des libelles."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


# Le moteur rend souvent "%" comme "0/0", "O/O", "9/0"... et la virgule
# decimale comme un point ou l'inverse.
_PCT_GARBLE = re.compile(r"[0oO9]\s*/\s*[0oO]")


def _clean_value_text(s: str) -> str:
    s = (s or "").replace(" ", " ").strip()
    s = _PCT_GARBLE.sub("%", s)
    return s


_NUM_RE = re.compile(r"(-?\d{1,5})[.,](\d{1,2})|(-?\d{1,5})")


def _parse_number(s: str) -> Optional[float]:
    """Premier nombre plausible d'un fragment de texte OCR."""
    s = _clean_value_text(s)
    # Colle les cas "21.30/0" -> "21.3 %" deja traites, puis lit le nombre
    m = _NUM_RE.search(s)
    if not m:
        return None
    if m.group(1) is not None:
        try:
            return float(f"{m.group(1)}.{m.group(2)}")
        except ValueError:
            return None
    try:
        return float(m.group(3))
    except (TypeError, ValueError):
        return None


# ─── Pretraitement des images ─────────────────────────────────────────────────
# Chaque variante rattrape ce que les autres ratent. L'ordre compte : la
# premiere qui lit une valeur l'emporte, les suivantes ne font que completer.

# Mesure faite sur des captures reelles : la RESOLUTION D'ORIGINE donne les
# meilleurs resultats (les petits nombres isoles comme la graisse viscerale
# disparaissent des qu'on agrandit), et elle est deux fois plus rapide. Les
# variantes agrandies ne servent que de rattrapage.
VARIANTS = [
    {"scale": 1.0, "mode": "gray"},   # meilleur rendement sur l'ecran Details
    {"scale": 1.5, "mode": "gray"},   # attrape le gros cadran (blanc sur turquoise)
    {"scale": 2.0, "mode": "bin"},
    {"scale": 3.0, "mode": "gray"},
]

# Au-dela, le moteur Windows decroche (images trop grandes) : on borne.
MAX_SIDE = 8000


def _preprocess(src: str, dst: str, scale: float, mode: str) -> bool:
    try:
        from PIL import Image, ImageOps, ImageEnhance
    except Exception as e:
        print(f"[sante] Pillow indisponible : {e}", flush=True)
        return False
    try:
        im = Image.open(src)
        # Les captures iPhone peuvent porter une rotation EXIF
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        im = im.convert("L")   # la couleur disparait : le texte vert, orange
                               # ou rouge de FitDays redevient lisible
        if mode == "raw":
            pass               # aucune retouche : c'est souvent le meilleur
        elif mode == "bin":
            im = ImageOps.autocontrast(im, cutoff=1)
            im = im.point(lambda p: 255 if p > 170 else 0)
        else:
            im = ImageOps.autocontrast(im, cutoff=1)
            im = ImageEnhance.Contrast(im).enhance(1.8)
        w, h = im.size
        f = min(scale, MAX_SIDE / max(w, h))
        if f > 1.0:
            im = im.resize((int(w * f), int(h * f)), Image.LANCZOS)
        im.save(dst)
        return True
    except Exception as e:
        print(f"[sante] pretraitement KO : {e}", flush=True)
        return False


# ─── Appel du moteur OCR ──────────────────────────────────────────────────────

def _ocr_script_path() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return str(Path(base) / "ocr_win.ps1")
    return str(Path(__file__).resolve().parent / "ocr_win.ps1")


def ocr_available() -> dict:
    """Le moteur OCR de Windows est-il utilisable sur ce poste ?"""
    if sys.platform != "win32":
        return {"ok": False, "error": "OCR disponible uniquement sous Windows."}
    if not Path(_ocr_script_path()).exists():
        return {"ok": False, "error": "Script OCR introuvable."}
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        return {"ok": False, "error": "Pillow requis pour préparer les images."}
    return {"ok": True}


def _run_ocr(image_path: str, timeout: int = 90) -> dict:
    """Lance ocr_win.ps1 et retourne {ok, words:[{t,x,y,w,h}], ...}."""
    out_fd, out_path = tempfile.mkstemp(prefix="pilote_ocr_", suffix=".json")
    os.close(out_fd)
    try:
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-File", _ocr_script_path(),
               "-ImagePath", str(image_path), "-JsonPath", out_path]
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(cmd, timeout=timeout, capture_output=True,
                       creationflags=flags)
        with open(out_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "OCR trop long (image trop grande ?)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass


# ─── Lecture d'une capture ────────────────────────────────────────────────────

def _rows_from_words(words: list) -> list:
    """
    Regroupe les mots en lignes horizontales.

    Deux mots appartiennent a la meme ligne si leurs centres verticaux sont
    distants de moins de 60 % de la hauteur du plus grand des deux. Ca tolere
    les libelles sur deux lignes tout en separant deux metriques voisines.
    """
    items = sorted(words, key=lambda w: (w.get("y", 0), w.get("x", 0)))
    rows = []
    for w in items:
        cy = w.get("y", 0) + w.get("h", 0) / 2.0
        placed = False
        for row in rows:
            tol = max(row["h"], w.get("h", 0)) * 0.6
            if abs(cy - row["cy"]) <= tol:
                row["words"].append(w)
                row["cy"] = sum(x.get("y", 0) + x.get("h", 0) / 2.0
                                for x in row["words"]) / len(row["words"])
                row["h"] = max(row["h"], w.get("h", 0))
                placed = True
                break
        if not placed:
            rows.append({"cy": cy, "h": w.get("h", 0), "words": [w]})
    for row in rows:
        row["words"].sort(key=lambda w: w.get("x", 0))
    rows.sort(key=lambda r: r["cy"])
    return rows


def _tokens(s: str) -> set:
    """Mots significatifs d'un libelle, sans accents ni ponctuation."""
    return {t for t in re.split(r"[^a-z0-9]+", _norm(s)) if len(t) > 1}


def _match_metric(label_text: str) -> Optional[str]:
    """
    Reconnait une metrique a partir du texte OCR d'un bloc de libelle.

    Comparaison par ENSEMBLE de mots, pas par sous-chaine : le moteur rend les
    mots d'un libelle sur deux lignes dans un ordre imprevisible ("Corporelle
    Eau") et y ajoute parfois du bruit ("Graisse sous- cutanee eee"). On exige
    que tous les mots de l'alias soient presents, et on retient l'alias le plus
    specifique — sans quoi "Poids sans graisse" serait reconnu comme "Poids".
    """
    toks = _tokens(label_text)
    if not toks:
        return None
    best, best_len = None, 0
    for m in METRICS:
        for alias in m["aliases"]:
            atoks = _tokens(alias)
            if atoks and atoks <= toks and len(atoks) > best_len:
                best, best_len = m["id"], len(atoks)
    return best


# Un libelle a gauche, sa valeur a droite. Mais FitDays coupe ses libelles
# longs sur DEUX lignes, et la valeur se retrouve alors sur la ligne du
# milieu :
#
#     Graisse            <- ligne 1 du libelle
#                21.3 %  <- la valeur, seule sur sa ligne
#     corporelle         <- ligne 2 du libelle
#
# Un appariement ligne a ligne rate donc la moitie des mesures. On raisonne
# en COLONNES : on reconstitue les blocs de libelle a gauche, puis on rattache
# chaque nombre de droite au bloc dont il chevauche la hauteur.

_VALUE_TOKEN = re.compile(r"^[-+]?\d")

# "15/09/2026" ou "08:37" commencent par un chiffre mais ne sont pas des
# valeurs : sans ce filtre, une date se retrouve enregistree comme mesure.
_NOT_A_VALUE = re.compile(r"[/:]")

# Frontiere entre la colonne des libelles et celle des valeurs.
_SPLIT_X = 0.45


def _label_blocks(words: list) -> list:
    """Regroupe les mots de gauche en blocs de libelle (1 ou 2 lignes)."""
    blocks = []
    for w in sorted(words, key=lambda w: (w.get("y", 0), w.get("x", 0))):
        top = w.get("y", 0)
        bot = top + w.get("h", 0)
        if blocks:
            b = blocks[-1]
            # Meme mot-ligne (chevauchement) ou ligne suivante tres proche :
            # c'est la suite du meme libelle.
            if top - b["bot"] < max(w.get("h", 0), b["h"]) * 0.75:
                b["words"].append(w)
                b["top"] = min(b["top"], top)
                b["bot"] = max(b["bot"], bot)
                b["h"]   = max(b["h"], w.get("h", 0))
                continue
        blocks.append({"top": top, "bot": bot, "h": w.get("h", 0), "words": [w]})
    for b in blocks:
        b["words"].sort(key=lambda w: (w.get("y", 0), w.get("x", 0)))
        b["text"] = " ".join(w.get("t", "") for w in b["words"])
    return blocks


def _validate(mid: str, val: float) -> Optional[float]:
    """
    Garde-fou : une valeur hors des bornes physiologiques est refusee.

    Le cas courant est le point decimal perdu par l'OCR ("152" pour 15.2) :
    on retente en divisant par 10. Si ca ne rentre toujours pas, on prefere
    ne rien ecrire plutot qu'inscrire une donnee de sante fausse.
    """
    rng = metric(mid).get("range")
    if not rng:
        return val
    lo, hi = rng
    if lo <= val <= hi:
        return val
    for factor in (10.0, 100.0):
        if lo <= val / factor <= hi:
            return round(val / factor, 2)
    return None


def _contraste_cutoff(words: list) -> Optional[int]:
    """
    Ordonnee du bloc "Contraste" de l'ecran principal FitDays.

    Ce bloc affiche les ECARTS depuis la pesee precedente (+1.2 kg, +0.4 %),
    pas des valeurs. Ses tuiles portent en plus leur libelle SOUS le chiffre,
    ce qui trompe l'appariement. Tout ce qui est en dessous est donc ignore.
    """
    ys = [w.get("y", 0) for w in words if "contraste" in _norm(w.get("t", ""))]
    return min(ys) if ys else None


def _dial_weight(words: list, cutoff: Optional[int]) -> Optional[float]:
    """
    Poids affiche dans le grand cadran de l'ecran principal.

    Il n'a pas de libelle a cote : on le reconnait a sa taille, tres superieure
    au reste de la page. Sert de repli quand seul l'ecran principal est fourni.
    """
    cands = [w for w in words
             if (cutoff is None or w.get("y", 0) < cutoff)
             and not _NOT_A_VALUE.search(w.get("t", ""))
             and _VALUE_TOKEN.match(_clean_value_text(w.get("t", "")))]
    if not cands:
        return None
    hauteurs = sorted(w.get("h", 0) for w in words if w.get("h", 0) > 0)
    if not hauteurs:
        return None
    mediane = hauteurs[len(hauteurs) // 2]
    plus_gros = max(cands, key=lambda w: w.get("h", 0))
    if plus_gros.get("h", 0) < mediane * 1.8:
        return None
    val = _parse_number(plus_gros.get("t", ""))
    return _validate("poids", val) if val is not None else None


def _extract_values(words: list, width: int) -> dict:
    """Apparie chaque nombre de la colonne droite au libelle qui lui fait face."""
    if not words:
        return {}
    cutoff = _contraste_cutoff(words)
    if cutoff is not None:
        words = [w for w in words if w.get("y", 0) < cutoff]
    split = (width or 1) * _SPLIT_X
    left  = [w for w in words if w.get("x", 0) < split]
    right = [w for w in words if w.get("x", 0) >= split]

    blocks = _label_blocks(left)
    # Ne garde que les blocs qui correspondent a une metrique connue
    labelled = []
    for b in blocks:
        mid = _match_metric(b["text"])
        if mid:
            labelled.append((mid, b))

    found = {}
    if not labelled:
        # Ecran principal : pas de tableau, mais le poids du grand cadran
        dial = _dial_weight(words, None)
        return {"poids": dial} if dial is not None else {}
    for w in sorted(right, key=lambda w: (w.get("y", 0), w.get("x", 0))):
        txt = _clean_value_text(w.get("t", ""))
        if not _VALUE_TOKEN.match(txt):
            continue          # "%", "kg", "0/0" seuls : ce n'est pas la valeur
        if _NOT_A_VALUE.search(txt):
            continue          # date ou heure
        val = _parse_number(txt)
        if val is None:
            continue
        cy = w.get("y", 0) + w.get("h", 0) / 2.0

        # Bloc dont la hauteur contient le nombre, sinon le plus proche
        best, best_d = None, None
        for mid, b in labelled:
            if b["top"] <= cy <= b["bot"]:
                d = 0.0
            else:
                d = min(abs(cy - b["top"]), abs(cy - b["bot"]))
            if best_d is None or d < best_d:
                best, best_d = mid, d
        if best is None:
            continue
        # Trop loin de tout libelle : ce nombre appartient a autre chose
        if best_d is not None and best_d > max(w.get("h", 1), 1) * 2.5:
            continue
        val = _validate(best, val)
        if val is not None:
            found.setdefault(best, val)

    if "poids" not in found:
        dial = _dial_weight(words, None)   # deja coupe plus haut
        if dial is not None:
            found["poids"] = dial
    return found


# "08:37 15/09/2026" sur l'ecran principal, ou "13/09/2026" ailleurs
_DATE_RE = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})")
_TIME_RE = re.compile(r"^([0-2]?\d)[:h]([0-5]\d)$")


def _extract_datetime(rows: list) -> dict:
    """
    Date et heure de la pesee.

    On prend la PREMIERE date rencontree de haut en bas : sur l'ecran FitDays,
    c'est celle de la mesure affichee. Les dates plus bas ("Contraste ...")
    designent une mesure anterieure et ne doivent pas l'emporter.
    """
    out = {"date": "", "time": ""}
    for row in rows:
        line = " ".join(w.get("t", "") for w in row["words"])
        if not out["date"]:
            m = _DATE_RE.search(line)
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    out["date"] = datetime.date(y, mo, d).isoformat()
                except ValueError:
                    pass
                # L'heure est souvent le mot juste avant, sur la meme ligne
                for w in row["words"]:
                    tm = _TIME_RE.match((w.get("t") or "").strip())
                    if tm:
                        out["time"] = f"{int(tm.group(1)):02d}:{tm.group(2)}"
                        break
        if out["date"]:
            break
    return out


def read_screenshot(path: str, deja_lues=None) -> dict:
    """
    Lit UNE capture : plusieurs passes OCR, fusionnees.

    `deja_lues` : metriques deja obtenues sur une autre capture, pour savoir
    quand s'arreter.

    Retourne {ok, values:{metric: valeur}, date, time, passes, engine}.
    """
    chk = ocr_available()
    if not chk["ok"]:
        return {"ok": False, "error": chk["error"], "values": {}}

    src = Path(path)
    if not src.exists():
        return {"ok": False, "error": "Image introuvable.", "values": {}}

    values, date_info, passes, lang = {}, {"date": "", "time": ""}, 0, ""
    known = set(deja_lues or ())
    tmpdir = tempfile.mkdtemp(prefix="pilote_ocr_")
    try:
        for i, var in enumerate(VARIANTS):
            # Tout est lu : inutile d'insister
            if len(set(values) | known) >= len(METRICS) and date_info["date"]:
                break
            prepped = os.path.join(tmpdir, f"p{i}.png")
            if not _preprocess(str(src), prepped, var["scale"], var["mode"]):
                continue
            res = _run_ocr(prepped)
            if not res.get("ok"):
                continue
            passes += 1
            lang = lang or res.get("lang", "")
            avant = len(values)
            for mid, val in _extract_values(res.get("words") or [],
                                            res.get("width") or 1).items():
                values.setdefault(mid, val)   # la 1re passe qui lit gagne
            if not date_info["date"]:
                date_info = _extract_datetime(_rows_from_words(res.get("words") or []))
            # Une passe qui n'apporte plus rien : les suivantes non plus, en
            # pratique. On s'arrete la plutot que de couter 3 secondes de plus.
            # Mais tant qu'on n'a RIEN lu, on tente toutes les variantes : une
            # capture difficile (texte blanc sur fond colore) ne cede parfois
            # qu'a la derniere.
            if passes >= 2 and len(values) == avant and values:
                break
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if passes == 0:
        return {"ok": False, "values": {},
                "error": "Le moteur OCR de Windows n'a pas répondu."}
    return {"ok": True, "values": values, "date": date_info.get("date", ""),
            "time": date_info.get("time", ""), "passes": passes, "engine": lang}


def read_screenshots(paths: list) -> dict:
    """
    Lit PLUSIEURS captures du meme instant (ecran principal + details).

    Les valeurs se completent d'une capture a l'autre. En cas de desaccord sur
    une meme metrique, la premiere lue l'emporte : c'est un signal qu'on
    remonte a l'UI plutot qu'un arbitrage silencieux.
    """
    values, conflicts, date_, time_, details = {}, {}, "", "", []
    for p in paths or []:
        if len(values) >= len(METRICS) and date_:
            details.append({"file": os.path.basename(p), "ok": True,
                            "found": 0, "error": "", "skipped": True})
            continue
        r = read_screenshot(p, deja_lues=set(values))
        details.append({"file": os.path.basename(p), "ok": r.get("ok"),
                        "found": len(r.get("values") or {}),
                        "error": r.get("error", "")})
        if not r.get("ok"):
            continue
        for mid, val in (r.get("values") or {}).items():
            if mid in values and abs(values[mid] - val) > 1e-9:
                conflicts.setdefault(mid, []).append(val)
            values.setdefault(mid, val)
        date_ = date_ or r.get("date", "")
        time_ = time_ or r.get("time", "")

    manquants = [m["id"] for m in METRICS if m["id"] not in values]
    return {"ok": bool(values), "values": values, "date": date_, "time": time_,
            "missing": manquants, "conflicts": conflicts, "files": details,
            "error": "" if values else "Aucune valeur reconnue sur ces captures."}


# ─── Objectifs ────────────────────────────────────────────────────────────────

def goal_progress(goal: dict, mesures: list) -> dict:
    """
    Avancement d'un objectif, en pourcentage du chemin parcouru.

    `start` est la valeur de depart (celle du jour ou l'objectif a ete cree si
    elle n'est pas fournie). Un objectif de perte et un objectif de gain se
    calculent pareil : distance parcourue / distance totale.
    """
    mid = goal.get("metric")
    target = goal.get("target")
    if mid is None or target is None:
        return {"pct": 0, "current": None, "start": None, "done": False}

    dated = sorted([m for m in mesures if m.get(mid) is not None],
                   key=lambda m: (m.get("date", ""), m.get("time", "")))
    current = dated[-1].get(mid) if dated else None

    start = goal.get("start")
    if start is None:
        created = goal.get("createdAt", "")[:10]
        avant = [m for m in dated if m.get("date", "") <= created] if created else []
        start = (avant[-1].get(mid) if avant else
                 (dated[0].get(mid) if dated else None))

    if current is None or start is None:
        return {"pct": 0, "current": current, "start": start, "done": False}

    total = float(target) - float(start)
    if abs(total) < 1e-9:
        return {"pct": 100, "current": current, "start": start, "done": True}
    fait = float(current) - float(start)
    pct = max(0.0, min(100.0, (fait / total) * 100.0))
    # Atteint = on a franchi la cible dans le bon sens
    done = (current <= target) if total < 0 else (current >= target)
    return {"pct": round(pct, 1), "current": current, "start": start, "done": done}
