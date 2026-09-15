"""
patrimoine.py — Module "Patrimoine" : vue consolidee de ce qu'on possede.

Pourquoi une saisie manuelle
────────────────────────────
L'agregation bancaire automatique (Bridge, Powens...) suppose un contrat pro,
des cles API et une validation reglementaire : hors de portee pour une app
locale. On saisit donc les soldes A LA MAIN, une fois par mois. Six chiffres
par mois suffisent a construire une courbe de patrimoine qui vaut de l'or au
bout de deux ans.

Ce qui n'est PAS saisi a la main
────────────────────────────────
Le PEA et le pret etudiant vivent deja dans l'app. Leurs lignes sont marquees
`auto` et l'UI les pre-remplit depuis les modules existants — pas de double
saisie, pas de risque d'incoherence.

Un releve est un INSTANTANE date. On ne recalcule jamais le passe : ce qui a
ete constate le 1er mars reste ce qui a ete constate le 1er mars.

Emplacement : <app_dir>/users/<slug>/patrimoine.json
Backup quotidien : <app_dir>/users/<slug>/backups_patrimoine/

Modele de donnees
─────────────────
comptes : {id, label, type, icon, color, auto:""|"pea"|"pret", archived:false, note}
releves : {id, compteId, date:"YYYY-MM-01", montant}
"""
from __future__ import annotations

import datetime

import jsonstore


# ─── Types de comptes ─────────────────────────────────────────────────────────
# `dette` est le seul type compte negativement dans le patrimoine net.

TYPES = [
    {"id": "livret",    "label": "Livret / Épargne",      "icon": "🏦", "color": "#2563eb",
     "dette": False},
    {"id": "pea",       "label": "PEA",                   "icon": "📈", "color": "#16a34a",
     "dette": False},
    {"id": "cto",       "label": "Compte-titres",         "icon": "📊", "color": "#0891b2",
     "dette": False},
    {"id": "av",        "label": "Assurance vie",         "icon": "🛡️", "color": "#7c3aed",
     "dette": False},
    {"id": "crypto",    "label": "Cryptomonnaies",        "icon": "🪙", "color": "#d97706",
     "dette": False},
    {"id": "courant",   "label": "Compte courant",        "icon": "💳", "color": "#64748b",
     "dette": False},
    {"id": "immo",      "label": "Immobilier",            "icon": "🏠", "color": "#65a30d",
     "dette": False},
    {"id": "salariale", "label": "Épargne salariale",     "icon": "🏢", "color": "#0d9488",
     "dette": False},
    {"id": "autre",     "label": "Autre actif",           "icon": "📦", "color": "#71717a",
     "dette": False},
    {"id": "dette",     "label": "Dette / Emprunt",       "icon": "🎓", "color": "#dc2626",
     "dette": True},
]

_TYPES_BY_ID = {t["id"]: t for t in TYPES}


def type_info(tid: str) -> dict:
    return _TYPES_BY_ID.get(tid, _TYPES_BY_ID["autre"])


def is_dette(tid: str) -> bool:
    return bool(type_info(tid).get("dette"))


# ─── Comptes crees d'office ───────────────────────────────────────────────────
# Ils sont alimentes par les autres modules : l'UI les pre-remplit, l'utilisateur
# confirme. On ne les cree qu'une fois (marqueur _seeded).

def _comptes_auto() -> list:
    return [
        {"id": "cpt_pea",  "label": "PEA",            "type": "pea",   "auto": "pea",
         "icon": "📈", "color": "#16a34a", "archived": False, "note": ""},
        {"id": "cpt_pret", "label": "Prêt étudiant",  "type": "dette", "auto": "pret",
         "icon": "🎓", "color": "#dc2626", "archived": False, "note": ""},
    ]


def default_data() -> dict:
    return {
        "_meta": {
            "version": 1,
            "schema": "patrimoine.v1",
            "createdAt":   datetime.date.today().isoformat(),
            "lastSavedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        "comptes": _comptes_auto(),
        "releves": [],
        "_seeded": True,
        "_nid":    {"compte": 1, "releve": 1},
    }


_store = jsonstore.JsonStore(
    filename="patrimoine.json",
    backup_dirname="backups_patrimoine",
    schema="patrimoine.v1",
    default_factory=default_data,
)


def get_patrimoine_path():
    return _store.path()


def load_data() -> dict:
    data = _store.load()
    # Un fichier cree avant l'introduction des comptes auto n'en a pas : on les
    # ajoute une seule fois, sans ecraser ce que l'utilisateur a pu modifier.
    if not data.get("_seeded"):
        existants = {c.get("auto") for c in data.get("comptes", []) if c.get("auto")}
        for c in _comptes_auto():
            if c["auto"] not in existants:
                data.setdefault("comptes", []).append(c)
        data["_seeded"] = True
    return data


def save_data(data: dict) -> None:
    _store.save(data)


# ─── Calculs ──────────────────────────────────────────────────────────────────

def mois_courant() -> str:
    """Date d'ancrage du releve du mois en cours, toujours le 1er."""
    d = datetime.date.today()
    return d.replace(day=1).isoformat()


def mois_precedent(iso: str) -> str:
    try:
        d = datetime.date.fromisoformat(iso)
    except Exception:
        d = datetime.date.today()
    d = d.replace(day=1)
    return (d - datetime.timedelta(days=1)).replace(day=1).isoformat()


def net_worth(data: dict, date_iso: str = None) -> dict:
    """
    Patrimoine net a une date donnee : actifs moins dettes.

    Pour chaque compte on prend son releve le PLUS RECENT a cette date ou
    avant. Un compte qu'on n'a pas mis a jour ce mois-ci compte donc toujours,
    avec sa derniere valeur connue — sans quoi le patrimoine s'effondrerait
    artificiellement chaque fois qu'on oublie une ligne.
    """
    date_iso = date_iso or mois_courant()
    comptes = {c["id"]: c for c in data.get("comptes", []) if not c.get("archived")}
    derniers = {}
    for r in data.get("releves", []):
        cid = r.get("compteId")
        if cid not in comptes or not r.get("date"):
            continue
        if r["date"] > date_iso:
            continue
        cur = derniers.get(cid)
        if cur is None or r["date"] > cur["date"]:
            derniers[cid] = r

    actifs = dettes = 0.0
    detail = []
    for cid, r in derniers.items():
        c = comptes[cid]
        montant = float(r.get("montant") or 0)
        if is_dette(c.get("type")):
            dettes += abs(montant)
        else:
            actifs += montant
        detail.append({"compteId": cid, "label": c.get("label"), "type": c.get("type"),
                       "montant": montant, "date": r["date"]})

    return {"date": date_iso, "actifs": actifs, "dettes": dettes,
            "net": actifs - dettes, "detail": detail}


def serie_mensuelle(data: dict, mois: int = 36) -> list:
    """Patrimoine net mois par mois, pour la courbe."""
    releves = [r for r in data.get("releves", []) if r.get("date")]
    if not releves:
        return []
    debut = min(r["date"] for r in releves)
    try:
        d = datetime.date.fromisoformat(debut).replace(day=1)
    except Exception:
        return []
    fin = datetime.date.today().replace(day=1)

    out = []
    while d <= fin and len(out) < mois + 1:
        nw = net_worth(data, d.isoformat())
        out.append({"date": d.isoformat(), "net": nw["net"],
                    "actifs": nw["actifs"], "dettes": nw["dettes"]})
        d = (d.replace(day=28) + datetime.timedelta(days=7)).replace(day=1)
    return out[-(mois + 1):]


def mois_saisi(data: dict, date_iso: str = None) -> bool:
    """Le releve de ce mois a-t-il ete fait ?"""
    date_iso = date_iso or mois_courant()
    return any(r.get("date") == date_iso for r in data.get("releves", []))
