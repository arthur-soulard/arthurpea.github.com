"""
formation.py — Module "Formation" : ce qui nourrit le CV.

Le module suit trois choses distinctes, qui n'ont pas le meme cycle de vie :

  * les FORMATIONS, qui ont un statut (a faire -> en cours -> terminee) et,
    une fois terminees, un certificat depose ;
  * les EXPERIENCES, PROJETS et COMPETENCES, qui n'ont pas d'axe de
    progression : ils existent, on les decrit, ils alimentent l'export CV.

D'ou le decoupage de l'UI en quatre onglets : les deux premiers trient les
formations par statut, le troisieme porte tout le reste, le quatrieme compte.

Ce qui n'est PAS suivi ici
──────────────────────────
Le cout d'une formation. Choix delibere : l'argent vit dans "Mes comptes", et
un meme chiffre saisi a deux endroits finit toujours par diverger. Reste le
drapeau `cpf`, qui est une info de reperage et pas un montant.

Les heures passees non plus : une formation a un statut, pas un compteur.
Un compteur d'heures se serait perime des la premiere semaine ou on oublie de
le tenir a jour, et un compteur faux vaut moins que pas de compteur.

Emplacement : <app_dir>/users/<slug>/formation.json
Backup quotidien : <app_dir>/users/<slug>/backups_formation/
Certificats      : <app_dir>/users/<slug>/certificats/

Les certificats sont COPIES dans le dossier utilisateur, pas references la ou
ils se trouvent. Un chemin vers Telechargements casse des qu'on range le
fichier, et surtout la sauvegarde USB ne l'embarquerait pas — or un certificat
est exactement le genre de chose qu'on ne peut pas regenerer.

Modele de donnees
─────────────────
formations  : {id, titre, organisme, url, description, domaineId, format,
               preuve, ects, cpf, dureeEstimee, statut, dateDebut, dateFin,
               dateEcheance, priorite, note, certificat:{fichier, nom, ajouteLe}}
experiences : {id, poste, employeur, lieu, debut, fin, missions[], note}
projets     : {id, nom, url, description, techno[], debut, fin, note}
competences : {id, label, categorie, niveau 1-4}
domaines    : {id, label, icon, color}
"""
from __future__ import annotations

import os
import re
import sys
import shutil
import datetime
import unicodedata
from pathlib import Path

import storage
import jsonstore


# ─── Catalogues ───────────────────────────────────────────────────────────────

STATUTS = [
    {"id": "todo",    "label": "À faire",   "icon": "○"},
    {"id": "encours", "label": "En cours",  "icon": "◐"},
    {"id": "fini",    "label": "Terminée",  "icon": "●"},
]

FORMATS = [
    {"id": "enligne",    "label": "En ligne",    "icon": "💻"},
    {"id": "presentiel", "label": "Présentiel",  "icon": "🏫"},
    {"id": "hybride",    "label": "Hybride",     "icon": "🔀"},
    {"id": "examen",     "label": "Examen",      "icon": "📝"},
]

# `poids` classe les preuves de la plus forte a la plus faible : c'est ce qui
# ordonne l'export CV et le graphique des statistiques. Un diplome et des ECTS
# ne se discutent pas ; un badge de MOOC, si.
PREUVES = [
    {"id": "diplome",       "label": "Diplôme",             "icon": "🎓", "poids": 5},
    {"id": "ects",          "label": "Crédits ECTS",        "icon": "🏛️", "poids": 4},
    {"id": "certification", "label": "Certification",       "icon": "🏅", "poids": 3},
    {"id": "attestation",   "label": "Attestation / badge", "icon": "📄", "poids": 2},
    {"id": "aucune",        "label": "Aucune preuve",       "icon": "·",  "poids": 1},
]

PRIORITES = [
    {"id": "haute",   "label": "Haute",   "color": "#dc2626"},
    {"id": "normale", "label": "Normale", "color": "#64748b"},
    {"id": "basse",   "label": "Un jour", "color": "#94a3b8"},
]

NIVEAUX = [
    {"id": 1, "label": "Notions"},
    {"id": 2, "label": "Intermédiaire"},
    {"id": 3, "label": "Avancé"},
    {"id": 4, "label": "Expert"},
]

DOMAINES_DEFAUT = [
    {"id": "dom_ia",        "label": "Intelligence artificielle", "icon": "🤖", "color": "#7c3aed"},
    {"id": "dom_dev",       "label": "Développement",             "icon": "💻", "color": "#2563eb"},
    {"id": "dom_data",      "label": "Data",                      "icon": "📊", "color": "#0891b2"},
    {"id": "dom_finance",   "label": "Finance",                   "icon": "📈", "color": "#16a34a"},
    {"id": "dom_marketing", "label": "Marketing",                 "icon": "📣", "color": "#d97706"},
    {"id": "dom_langue",    "label": "Langues",                   "icon": "🗣️", "color": "#db2777"},
    {"id": "dom_soft",      "label": "Management & soft skills",  "icon": "🤝", "color": "#0d9488"},
    {"id": "dom_autre",     "label": "Autre",                     "icon": "📦", "color": "#71717a"},
]

CATEGORIES_COMPETENCE = [
    "Langages", "Outils & frameworks", "Data & IA", "Finance", "Langues", "Autre",
]


# ─── Formations livrees au premier lancement ──────────────────────────────────
# Un onglet vide ne dit pas ce qu'on peut y mettre. Ces lignes sont un point de
# depart a corriger, pas une recommandation gravee : les URL, les durees et les
# tarifs bougent, l'utilisateur les ajuste.

def _seed_formations() -> list:
    return [
        {"id": "f1", "titre": "GitHub Foundations", "organisme": "GitHub",
         "url": "https://resources.github.com/learn/certifications/",
         "description": "Examen surveille et payant : la seule de la liste qui soit "
                        "verifiable par un recruteur. A passer en premier.",
         "domaineId": "dom_dev", "format": "examen", "preuve": "certification",
         "ects": None, "cpf": False, "dureeEstimee": 20, "statut": "todo",
         "priorite": "haute"},
        {"id": "f2", "titre": "Google AI Essentials", "organisme": "Google",
         "url": "https://grow.google/ai-essentials/",
         "description": "La plus substantielle des introductions a l'IA, et la "
                        "marque la plus lisible sur un CV.",
         "domaineId": "dom_ia", "format": "enligne", "preuve": "attestation",
         "ects": None, "cpf": False, "dureeEstimee": 10, "statut": "todo",
         "priorite": "haute"},
        {"id": "f3", "titre": "Introduction à l'IA responsable", "organisme": "Google Cloud",
         "url": "https://www.cloudskillsboost.google/",
         "description": "Une heure. L'angle ethique et gouvernance est le seul qui "
                        "ne fasse doublon avec aucune autre introduction.",
         "domaineId": "dom_ia", "format": "enligne", "preuve": "attestation",
         "ects": None, "cpf": False, "dureeEstimee": 1, "statut": "todo",
         "priorite": "normale"},
        {"id": "f4", "titre": "Azure AI Fundamentals (AI-900)", "organisme": "Microsoft",
         "url": "https://learn.microsoft.com/credentials/certifications/azure-ai-fundamentals/",
         "description": "Le premier vrai examen technique en IA. La marche au-dessus "
                        "des MOOC d'introduction, pour environ 100 €.",
         "domaineId": "dom_ia", "format": "examen", "preuve": "certification",
         "ects": None, "cpf": False, "dureeEstimee": 25, "statut": "todo",
         "priorite": "normale"},
        {"id": "f5", "titre": "Les fondamentaux de l'intelligence artificielle",
         "organisme": "IBM SkillsBuild", "url": "https://skillsbuild.org/",
         "description": "Introduction gratuite avec badge Credly. Recouvre largement "
                        "Google AI Essentials — en faire une des deux suffit.",
         "domaineId": "dom_ia", "format": "enligne", "preuve": "attestation",
         "ects": None, "cpf": False, "dureeEstimee": 8, "statut": "todo",
         "priorite": "basse"},
        {"id": "f6", "titre": "L'essentiel de l'IA générative",
         "organisme": "Microsoft & LinkedIn", "url": "https://www.linkedin.com/learning/",
         "description": "Parcours LinkedIn Learning, attestation affichable sur le "
                        "profil. Meme terrain que les deux precedentes.",
         "domaineId": "dom_ia", "format": "enligne", "preuve": "attestation",
         "ects": None, "cpf": False, "dureeEstimee": 6, "statut": "todo",
         "priorite": "basse"},
        {"id": "f7", "titre": "Digital Marketing", "organisme": "HubSpot Academy",
         "url": "https://academy.hubspot.com/",
         "description": "Solide et reconnue — mais dans le marketing. N'a de valeur "
                        "que si le CV vise ce terrain.",
         "domaineId": "dom_marketing", "format": "enligne", "preuve": "certification",
         "ects": None, "cpf": False, "dureeEstimee": 12, "statut": "todo",
         "priorite": "basse"},
        {"id": "f8", "titre": "UE machine learning (à choisir)", "organisme": "CNAM",
         "url": "https://www.cnam.fr/",
         "description": "La seule piste de la liste qui donne des ECTS capitalisables. "
                        "Cours du soir ou a distance, une UE a la fois.",
         "domaineId": "dom_data", "format": "hybride", "preuve": "ects",
         "ects": 6, "cpf": True, "dureeEstimee": 60, "statut": "todo",
         "priorite": "normale"},
    ]


def _normalise_formation(f: dict) -> dict:
    """Complete une formation avec les cles que le JS attend toujours."""
    f.setdefault("titre", "")
    f.setdefault("organisme", "")
    f.setdefault("url", "")
    f.setdefault("description", "")
    f.setdefault("domaineId", "dom_autre")
    f.setdefault("format", "enligne")
    f.setdefault("preuve", "attestation")
    f.setdefault("ects", None)
    f.setdefault("cpf", False)
    f.setdefault("dureeEstimee", None)
    f.setdefault("statut", "todo")
    f.setdefault("dateDebut", "")
    f.setdefault("dateFin", "")
    f.setdefault("dateEcheance", "")
    f.setdefault("priorite", "normale")
    f.setdefault("note", "")
    f.setdefault("certificat", None)
    return f


def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "formation.v1",
            "createdAt":   datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "formations":  [_normalise_formation(f) for f in _seed_formations()],
        "experiences": [],
        "projets":     [],
        "competences": [],
        "domaines":    [dict(d) for d in DOMAINES_DEFAUT],
        "_nid": {"f": 9, "exp": 1, "proj": 1, "comp": 1, "dom": 1},
    }


_store = jsonstore.JsonStore(
    filename="formation.json",
    backup_dirname="backups_formation",
    schema="formation.v1",
    default_factory=default_data,
)


def load_data() -> dict:
    data = _store.load()
    for key in ("formations", "experiences", "projets", "competences", "domaines"):
        if not isinstance(data.get(key), list):
            data[key] = []
    # Un fichier dont on aurait supprime tous les domaines ne doit pas laisser
    # les formations orphelines sans libelle.
    if not data["domaines"]:
        data["domaines"] = [dict(d) for d in DOMAINES_DEFAUT]
    data["formations"] = [_normalise_formation(f) for f in data["formations"]]
    return data


def save_data(data: dict) -> None:
    _store.save(data)


# ─── Certificats ──────────────────────────────────────────────────────────────

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"}
MAX_BYTES   = 25 * 1024 * 1024          # 25 Mo : un certificat scanne tient large


def certificats_dir() -> Path:
    d = storage.get_user_dir() / "certificats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    """Nom de fichier sans accent, sans separateur, borne en longueur."""
    name = unicodedata.normalize("NFKD", name or "")
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return (name or "certificat")[:60]


def _resolve(fichier: str) -> Path:
    """
    Chemin d'un certificat, confine au dossier certificats/.

    Le nom vient du JSON, donc potentiellement d'un fichier edite a la main :
    on refuse tout ce qui contient un separateur ou remonte d'un cran, comme
    la protection zip-slip de sauvegarde.py.
    """
    fichier = (fichier or "").strip()
    if not fichier or fichier != os.path.basename(fichier) or fichier in (".", ".."):
        raise ValueError("Nom de certificat invalide.")
    base = certificats_dir().resolve()
    p = (base / fichier).resolve()
    if p.parent != base:
        raise ValueError("Nom de certificat invalide.")
    return p


def add_certificat(src_path: str, formation_id: str) -> dict:
    """Copie un fichier dans certificats/ et renvoie sa fiche."""
    src = Path(src_path)
    if not src.is_file():
        return {"ok": False, "error": "Fichier introuvable."}
    ext = src.suffix.lower()
    if ext not in ALLOWED_EXT:
        return {"ok": False, "error": "Format non accepté (%s)." % (ext or "sans extension")}
    size = src.stat().st_size
    if size > MAX_BYTES:
        return {"ok": False, "error": "Fichier trop lourd (%d Mo, maximum %d Mo)."
                                      % (size // (1024 * 1024), MAX_BYTES // (1024 * 1024))}

    fid = _safe_name(formation_id) or "f"
    dest = certificats_dir() / ("%s_%s%s" % (fid, _safe_name(src.stem), ext))
    # Un seul certificat par formation : les anciens fichiers du meme id partent.
    for old in certificats_dir().glob("%s_*" % fid):
        if old != dest:
            try:
                old.unlink()
            except Exception:
                pass
    shutil.copy2(str(src), str(dest))
    return {"ok": True, "certificat": {
        "fichier":  dest.name,
        "nom":      src.name,
        "taille":   size,
        "ajouteLe": datetime.date.today().isoformat(),
    }}


def remove_certificat(fichier: str) -> dict:
    try:
        p = _resolve(fichier)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        if p.exists():
            p.unlink()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_certificat(fichier: str) -> dict:
    try:
        p = _resolve(fichier)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not p.exists():
        return {"ok": False, "error": "Le certificat n'est plus sur le disque."}
    try:
        if sys.platform == "win32":
            os.startfile(str(p))
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def certificats_state(data: dict) -> dict:
    """
    Etat du dossier certificats/ : ce qui manque, ce qui traine.

    Supprimer une formation ne supprime pas son certificat — comme delete_user
    qui conserve le dossier de l'utilisateur. Le menage se fait a la demande,
    depuis Parametres, et cette fonction dit ce qu'il y a a nettoyer.
    """
    refs, manquants = set(), []
    for f in data.get("formations", []):
        c = f.get("certificat") or {}
        if not c.get("fichier"):
            continue
        refs.add(c["fichier"])
        try:
            existe = _resolve(c["fichier"]).exists()
        except ValueError:
            existe = False
        if not existe:
            manquants.append({"id": f.get("id"), "titre": f.get("titre"),
                              "fichier": c["fichier"]})

    orphelins, poids = [], 0
    try:
        for p in certificats_dir().iterdir():
            if not p.is_file():
                continue
            taille = p.stat().st_size
            poids += taille
            if p.name not in refs:
                orphelins.append({"fichier": p.name, "taille": taille})
    except Exception:
        pass

    return {"ok": True, "dossier": str(certificats_dir()), "poids": poids,
            "total": len(refs), "orphelins": orphelins, "manquants": manquants}


def clean_orphans(data: dict) -> dict:
    """Supprime les certificats qu'aucune formation ne reference plus."""
    state = certificats_state(data)
    n = 0
    for o in state.get("orphelins", []):
        if remove_certificat(o["fichier"]).get("ok"):
            n += 1
    return {"ok": True, "supprimes": n}
