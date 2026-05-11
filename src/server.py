"""
server.py — Serveur local de cours boursiers (Yahoo Finance), version embarquee.

Adapte de cours_server_v4.py pour etre :
  - Demarre/arrete proprement par app.py (start_server / stop_server)
  - Capable de choisir un port libre automatiquement si le defaut est occupe
  - Tournant en thread daemon (meurt avec le process principal)

Endpoints (memes que avant) :
  GET /cours?tickers=EPA:ESE,EPA:SGO    -> cours actuels + variations w/m/y
  GET /history?tickers=EPA:ESE          -> historique journalier (range=max)
  GET /ping                              -> health check
"""
from __future__ import annotations

import os
import http.server
import http.cookiejar
import hashlib
import json
import socket
import threading
import time
import datetime
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed


DEFAULT_PORT = 7438
HOST = "127.0.0.1"
CACHE_TTL         = 60     # secondes entre 2 appels Yahoo (cours actuels)
HISTORY_CACHE_TTL = 3600   # 1h entre 2 fetches d'historique

# Suffixes Yahoo selon la place
TICKER_MAP = {
    "EPA:": ".PA",
    "AMS:": ".AS",
    "ETR:": ".DE",
    "LON:": ".L",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ─── Etat interne ─────────────────────────────────────────────────────────────

_cache         = {}            # {yahoo_ticker: {prix, w1, m1, y1, ts}}
_history_cache = {}            # {yahoo_ticker: {dates, closes, ts}}
_lock          = threading.Lock()

_server_instance = None  # type: ignore  # http.server.ThreadingHTTPServer
_server_thread   = None  # type: ignore  # threading.Thread
_server_port     = DEFAULT_PORT
_html_file_path  = None  # type: ignore  # str: chemin absolu vers index.html


def to_yahoo(ticker: str) -> str:
    for prefix, suffix in TICKER_MAP.items():
        if ticker.upper().startswith(prefix):
            return ticker[len(prefix):] + suffix
    return ticker


# ─── Cours actuels ────────────────────────────────────────────────────────────

def fetch_yahoo(yahoo_ticker: str):
    for host in ("query1", "query2"):
        try:
            # range=1y pour pouvoir calculer w1 (5j), m1 (22j) ET y1 (252j)
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                + urllib.parse.quote(yahoo_ticker)
                + "?interval=1d&range=1y&events=history"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())

            result = data.get("chart", {}).get("result")
            if not result:
                continue

            meta   = result[0].get("meta", {})
            closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]
            if not closes:
                continue

            prix = meta.get("regularMarketPrice") or closes[-1]

            def pct(old, new):
                if old and old != 0:
                    return round((new - old) / old * 100, 2)
                return None

            n  = len(closes)
            # d1 : on utilise regularMarketChangePercent (calcul natif Yahoo, gère
            # les jours fériés et ajustements). Fallback sur chartPreviousClose si absent.
            d1_raw = meta.get("regularMarketChangePercent")
            if d1_raw is not None:
                d1 = round(d1_raw, 2)
            else:
                prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                d1 = pct(prev, prix) if prev else None
            w1 = pct(closes[-6],  prix) if n >= 6   else None
            m1 = pct(closes[-22], prix) if n >= 22  else None
            y1 = pct(closes[0],   prix) if n >= 200 else None

            return {"prix": round(prix, 4), "d1": d1, "w1": w1, "m1": m1, "y1": y1}
        except Exception as e:
            print(f"[server] Yahoo/{host} KO {yahoo_ticker}: {e}", flush=True)
            continue
    return None


def get_prices(tickers):
    result, now = {}, time.time()
    to_fetch = []
    for tk in tickers:
        ytk = to_yahoo(tk)
        with _lock:
            cached = _cache.get(ytk)
            if cached and (now - cached["ts"]) < CACHE_TTL:
                result[tk] = cached
                continue
        to_fetch.append(tk)

    if not to_fetch:
        return result

    def _fetch_one(tk):
        ytk = to_yahoo(tk)
        data = fetch_yahoo(ytk)
        if data:
            data["ts"] = time.time()
            with _lock:
                _cache[ytk] = data
        return tk, data

    with ThreadPoolExecutor(max_workers=min(len(to_fetch), 8)) as ex:
        futures = {ex.submit(_fetch_one, tk): tk for tk in to_fetch}
        for fut in as_completed(futures):
            tk, data = fut.result()
            if data:
                result[tk] = data

    return result


# ─── Historiques ──────────────────────────────────────────────────────────────

def fetch_yahoo_history(yahoo_ticker: str, range_param: str = "max", interval: str = "1d"):
    for host in ("query1", "query2"):
        try:
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                + urllib.parse.quote(yahoo_ticker)
                + f"?interval={interval}&range={range_param}&events=history"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())

            result = data.get("chart", {}).get("result")
            if not result:
                continue

            timestamps = result[0].get("timestamp", [])
            closes_raw = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if not timestamps or not closes_raw:
                continue

            dates, closes = [], []
            for ts, c in zip(timestamps, closes_raw):
                if c is None:
                    continue
                d = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                dates.append(d)
                closes.append(round(c, 4))
            if not dates:
                continue

            return {"dates": dates, "closes": closes}
        except Exception as e:
            print(f"[server] Yahoo/history/{host} KO {yahoo_ticker}: {e}", flush=True)
            continue
    return None


def get_history(tickers, range_param: str = "max"):
    """Cache separe par range pour permettre du daily sur les courtes plages."""
    cache_key_suffix = f"::{range_param}"
    result, now = {}, time.time()
    for tk in tickers:
        ytk = to_yahoo(tk)
        cache_key = ytk + cache_key_suffix
        with _lock:
            cached = _history_cache.get(cache_key)
            if cached and (now - cached["ts"]) < HISTORY_CACHE_TTL:
                result[tk] = {"dates": cached["dates"], "closes": cached["closes"]}
                continue
        data = fetch_yahoo_history(ytk, range_param=range_param, interval="1d")
        if data:
            with _lock:
                _history_cache[cache_key] = {**data, "ts": now}
            result[tk] = data
    return result


# ─── Avis analystes & objectifs de cours ─────────────────────────────────────

ANALYSTS_CACHE_TTL = 3600 * 6   # 6h, les analystes ne bougent pas tous les jours
_analysts_cache = {}            # {yahoo_ticker: {data, ts}}

SEARCH_CACHE_TTL = 300          # 5 min — les résultats de recherche ne changent pas souvent
_search_cache = {}              # {query_normalisee: {results, ts}}

# Session HTTP partagee : Yahoo exige un cookie + crumb depuis 2024
_yahoo_opener = None
_yahoo_crumb  = None
_yahoo_lock   = threading.Lock()


def _ensure_yahoo_session():
    """
    Initialise une session avec cookies + crumb pour acceder a quoteSummary.
    Voir https://github.com/ranaroussi/yfinance/issues/1737
    """
    global _yahoo_opener, _yahoo_crumb
    with _yahoo_lock:
        if _yahoo_opener and _yahoo_crumb:
            return _yahoo_opener, _yahoo_crumb

        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [
            ("User-Agent", USER_AGENT),
            ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
            ("Accept-Language", "fr-FR,fr;q=0.9,en;q=0.8"),
        ]

        # 1. Pose les cookies (consentement EU automatique)
        try:
            opener.open("https://fc.yahoo.com/", timeout=10).read()
        except Exception:
            pass
        try:
            opener.open("https://finance.yahoo.com/", timeout=10).read()
        except Exception:
            pass

        # 2. Recupere le crumb
        crumb = None
        try:
            with opener.open(
                "https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10
            ) as resp:
                crumb = resp.read().decode().strip()
        except Exception as e:
            print(f"[server] Crumb KO: {e}", flush=True)

        if not crumb:
            return None, None

        _yahoo_opener = opener
        _yahoo_crumb  = crumb
        return opener, crumb


# ─── PIN (fichier dedie ultra-simple) ────────────────────────────────────────

_PIN_SALT = "Suivi_PEA_pin_salt_v2"


def _pin_path():
    """Chemin du fichier hash PIN (a cote du pea_data.json du profil actif)."""
    import storage as _storage
    return _storage.get_app_dir() / "pin.hash"


def _pin_hash(pin_str: str) -> str:
    return hashlib.sha256((_PIN_SALT + "::" + pin_str).encode()).hexdigest()


def pin_required() -> bool:
    p = _pin_path()
    return p.exists() and p.stat().st_size > 0


def pin_set(pin_str: str) -> None:
    p = _pin_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not pin_str:
        # Suppression du PIN
        if p.exists():
            try: p.unlink()
            except Exception: pass
        return
    with open(p, "w", encoding="utf-8") as f:
        f.write(_pin_hash(pin_str))


def pin_check(pin_str: str) -> bool:
    p = _pin_path()
    if not p.exists():
        return True  # pas de PIN → toujours OK
    try:
        with open(p, "r", encoding="utf-8") as f:
            stored = f.read().strip()
        return stored == _pin_hash(pin_str)
    except Exception:
        return False


# ─── Sparkline 30 jours ──────────────────────────────────────────────────────

SPARK_CACHE_TTL = 3600  # 1h
_spark_cache = {}


def fetch_yahoo_sparkline(yahoo_ticker: str):
    """Recupere les ~30 derniers cours de cloture (range=1mo)."""
    for host in ("query1", "query2"):
        try:
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/"
                + urllib.parse.quote(yahoo_ticker)
                + "?interval=1d&range=1mo"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            result = data.get("chart", {}).get("result")
            if not result:
                continue
            closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
            closes = [c for c in closes if c is not None]
            if not closes:
                continue
            return closes
        except Exception as e:
            print(f"[server] spark/{host} {yahoo_ticker}: {e}", flush=True)
    return None


def get_sparklines(tickers):
    out, now = {}, time.time()
    for tk in tickers:
        ytk = to_yahoo(tk)
        with _lock:
            cached = _spark_cache.get(ytk)
            if cached and (now - cached["ts"]) < SPARK_CACHE_TTL:
                out[tk] = cached["closes"]
                continue
        closes = fetch_yahoo_sparkline(ytk)
        if closes:
            with _lock:
                _spark_cache[ytk] = {"closes": closes, "ts": now}
            out[tk] = closes
    return out


# ─── Key stats (PER, dividend yield, 52-week range) ──────────────────────────

KEYSTATS_CACHE_TTL = 3600 * 6   # 6h
_keystats_cache = {}


def fetch_yahoo_keystats(yahoo_ticker: str):
    """summaryDetail + defaultKeyStatistics : PER, yield, market cap, range 52W."""
    opener, crumb = _ensure_yahoo_session()
    if not opener or not crumb:
        return None
    for host in ("query1", "query2"):
        try:
            url = (
                f"https://{host}.finance.yahoo.com/v10/finance/quoteSummary/"
                + urllib.parse.quote(yahoo_ticker)
                + "?modules=summaryDetail,defaultKeyStatistics,price"
                + "&crumb=" + urllib.parse.quote(crumb)
            )
            with opener.open(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            result = data.get("quoteSummary", {}).get("result")
            if not result:
                continue
            sd  = result[0].get("summaryDetail",        {}) or {}
            ks  = result[0].get("defaultKeyStatistics", {}) or {}
            pr  = result[0].get("price",                {}) or {}
            def _v(d, k):
                obj = d.get(k)
                if isinstance(obj, dict): return obj.get("raw")
                return obj
            out = {
                "trailingPE":   _v(sd, "trailingPE"),
                "forwardPE":    _v(sd, "forwardPE")  or _v(ks, "forwardPE"),
                "divYield":     _v(sd, "dividendYield") or _v(sd, "trailingAnnualDividendYield"),
                "marketCap":    _v(pr, "marketCap")  or _v(sd, "marketCap"),
                "fiftyTwoWeekHigh": _v(sd, "fiftyTwoWeekHigh"),
                "fiftyTwoWeekLow":  _v(sd, "fiftyTwoWeekLow"),
                "currency":     pr.get("currency") or sd.get("currency"),
            }
            # Si tout est None c'est probablement un ETF ou un ticker invalide
            if all(v is None for k,v in out.items() if k != "currency"):
                return None
            return out
        except Exception as e:
            print(f"[server] keystats/{host} {yahoo_ticker}: {e}", flush=True)
    return None


def get_keystats(tickers):
    out, now = {}, time.time()
    for tk in tickers:
        ytk = to_yahoo(tk)
        with _lock:
            cached = _keystats_cache.get(ytk)
            if cached and (now - cached["ts"]) < KEYSTATS_CACHE_TTL:
                out[tk] = cached["data"]
                continue
        data = fetch_yahoo_keystats(ytk)
        if data is not None:
            with _lock:
                _keystats_cache[ytk] = {"data": data, "ts": now}
            out[tk] = data
    return out


# ─── Recherche / autocomplete ticker Yahoo ───────────────────────────────────

# Mini-index local des ETF PEA populaires souvent mal classes par Yahoo.
# Format : {tag de recherche en minuscule: [(symbol, shortname), ...]}
# Plus le tag est specifique, plus le boost est fort.
PEA_ETF_BOOST = {
    "msci world":  [("WPEA.PA",  "Amundi PEA MSCI World UCITS ETF"),
                    ("CW8.PA",   "Amundi MSCI World UCITS ETF"),
                    ("EWLD.PA",  "Lyxor MSCI World UCITS ETF")],
    "world":       [("WPEA.PA",  "Amundi PEA MSCI World UCITS ETF"),
                    ("CW8.PA",   "Amundi MSCI World UCITS ETF"),
                    ("EWLD.PA",  "Lyxor MSCI World UCITS ETF")],
    "s&p 500":     [("ESE.PA",   "Amundi S&P 500 UCITS ETF"),
                    ("PE500.PA", "BNP Paribas Easy S&P 500 UCITS ETF"),
                    ("PSP5.PA",  "Amundi PEA S&P 500 UCITS ETF")],
    "s&p":         [("ESE.PA",   "Amundi S&P 500 UCITS ETF"),
                    ("PE500.PA", "BNP Paribas Easy S&P 500 UCITS ETF"),
                    ("PSP5.PA",  "Amundi PEA S&P 500 UCITS ETF")],
    "sp500":       [("ESE.PA",   "Amundi S&P 500 UCITS ETF"),
                    ("PSP5.PA",  "Amundi PEA S&P 500 UCITS ETF")],
    "nasdaq":      [("PANX.PA",  "Amundi NASDAQ 100 UCITS ETF"),
                    ("PUST.PA",  "BNP Paribas Easy NASDAQ 100 UCITS ETF")],
    "cac 40":      [("CAC.PA",   "Lyxor CAC 40 UCITS ETF"),
                    ("PCEH.PA",  "Amundi CAC 40 UCITS ETF")],
    "cac":         [("CAC.PA",   "Lyxor CAC 40 UCITS ETF"),
                    ("PCEH.PA",  "Amundi CAC 40 UCITS ETF")],
    "stoxx":       [("ETZ.PA",   "Amundi STOXX Europe 600 UCITS ETF"),
                    ("MFEC.PA",  "Lyxor STOXX Europe 600 UCITS ETF")],
    "stoxx 600":   [("ETZ.PA",   "Amundi STOXX Europe 600 UCITS ETF")],
    "europe 600":  [("ETZ.PA",   "Amundi STOXX Europe 600 UCITS ETF")],
    "emerging":    [("PAEEM.PA", "Amundi MSCI Emerging Markets UCITS ETF"),
                    ("PEMS.PA",  "BNP Paribas Easy MSCI Emerging UCITS ETF")],
    "emergents":   [("PAEEM.PA", "Amundi MSCI Emerging Markets UCITS ETF")],
}

# Index des principales actions CAC 40 / SBF 120 (Yahoo ne renvoie pas toujours
# la cotation Paris pour les recherches textuelles, donc on prend les devants).
# Format : {mot-cle minuscule: (ticker.PA, nom complet)}
PEA_STOCK_INDEX = {
    # CAC 40
    "airbus":                ("AIR.PA",  "Airbus SE"),
    "air liquide":           ("AI.PA",   "Air Liquide"),
    "arcelormittal":         ("MT.PA",   "ArcelorMittal"),
    "axa":                   ("CS.PA",   "AXA"),
    "bnp paribas":           ("BNP.PA",  "BNP Paribas"),
    "bnp":                   ("BNP.PA",  "BNP Paribas"),
    "bouygues":              ("EN.PA",   "Bouygues"),
    "bureau veritas":        ("BVI.PA",  "Bureau Veritas"),
    "capgemini":             ("CAP.PA",  "Capgemini"),
    "carrefour":             ("CA.PA",   "Carrefour"),
    "credit agricole":       ("ACA.PA",  "Crédit Agricole"),
    "danone":                ("BN.PA",   "Danone"),
    "dassault":              ("AM.PA",   "Dassault Aviation"),
    "edenred":               ("EDEN.PA", "Edenred"),
    "engie":                 ("ENGI.PA", "Engie"),
    "essilor":               ("EL.PA",   "EssilorLuxottica"),
    "eurofins":              ("ERF.PA",  "Eurofins Scientific"),
    "hermès":                ("RMS.PA",  "Hermès International"),
    "hermes":                ("RMS.PA",  "Hermès International"),
    "kering":                ("KER.PA",  "Kering"),
    "legrand":               ("LR.PA",   "Legrand"),
    "loreal":                ("OR.PA",   "L'Oréal"),
    "l'oréal":               ("OR.PA",   "L'Oréal"),
    "lvmh":                  ("MC.PA",   "LVMH Moët Hennessy Louis Vuitton"),
    "michelin":              ("ML.PA",   "Michelin"),
    "orange":                ("ORA.PA",  "Orange"),
    "pernod ricard":         ("RI.PA",   "Pernod Ricard"),
    "publicis":              ("PUB.PA",  "Publicis Groupe"),
    "renault":               ("RNO.PA",  "Renault"),
    "safran":                ("SAF.PA",  "Safran"),
    "saint-gobain":          ("SGO.PA",  "Saint-Gobain"),
    "saint gobain":          ("SGO.PA",  "Saint-Gobain"),
    "sanofi":                ("SAN.PA",  "Sanofi"),
    "schneider":             ("SU.PA",   "Schneider Electric"),
    "société générale":      ("GLE.PA",  "Société Générale"),
    "societe generale":      ("GLE.PA",  "Société Générale"),
    "stellantis":            ("STLAP.PA","Stellantis"),
    "stmicro":               ("STMPA.PA","STMicroelectronics"),
    "teleperformance":       ("TEP.PA",  "Teleperformance"),
    "thales":                ("HO.PA",   "Thales"),
    "totalenergies":         ("TTE.PA",  "TotalEnergies"),
    "total":                 ("TTE.PA",  "TotalEnergies"),
    "veolia":                ("VIE.PA",  "Veolia Environnement"),
    "vinci":                 ("DG.PA",   "Vinci"),
    "vivendi":               ("VIV.PA",  "Vivendi"),
    # SBF 120 / Autres
    "alstom":                ("ALO.PA",  "Alstom"),
    "amundi":                ("AMUN.PA", "Amundi"),
    "bic":                   ("BB.PA",   "Bic"),
    "biomerieux":            ("BIM.PA",  "bioMérieux"),
    "casino":                ("CO.PA",   "Casino Guichard"),
    "covivio":               ("COV.PA",  "Covivio"),
    "edf":                   ("EDF.PA",  "Électricité de France"),
    "elis":                  ("ELIS.PA", "Elis"),
    "eutelsat":              ("ETL.PA",  "Eutelsat Communications"),
    "faurecia":              ("FRVIA.PA","Forvia"),
    "forvia":                ("FRVIA.PA","Forvia"),
    "getlink":               ("GET.PA",  "Getlink"),
    "iliad":                 ("ILD.PA",  "Iliad"),
    "ipsen":                 ("IPN.PA",  "Ipsen"),
    "jc decaux":             ("DEC.PA",  "JCDecaux"),
    "klepierre":             ("LI.PA",   "Klépierre"),
    "lagardere":             ("MMB.PA",  "Lagardère"),
    "natixis":               ("KN.PA",   "Natixis"),
    "nexity":                ("NXI.PA",  "Nexity"),
    "rexel":                 ("RXL.PA",  "Rexel"),
    "scor":                  ("SCR.PA",  "SCOR"),
    "soitec":                ("SOI.PA",  "Soitec"),
    "spie":                  ("SPIE.PA", "Spie"),
    "suez":                  ("SEV.PA",  "Suez"),
    "ubisoft":               ("UBI.PA",  "Ubisoft Entertainment"),
    "valneva":               ("VLA.PA",  "Valneva"),
    "vallourec":             ("VK.PA",   "Vallourec"),
    "veolia":                ("VIE.PA",  "Veolia"),
    "verallia":              ("VRLA.PA", "Verallia"),
    "worldline":             ("WLN.PA",  "Worldline"),
}


def _normalize_search(s: str) -> str:
    """Lowercase + retire accents + retire apostrophes/tirets pour matcher
    'L'Oreal' avec 'loreal', 'Saint-Gobain' avec 'saint gobain', etc."""
    import unicodedata
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # strip accents
    s = s.replace("'", "").replace("'", "").replace("-", " ").strip()
    return " ".join(s.split())  # collapse spaces

# Alias utilisé pour la clé de cache de recherche
_normalize_query = _normalize_search


def _boost_local_etf(query: str) -> list:
    """Cherche dans l'index local ETF + actions CAC/SBF. Pre-classe en tete."""
    q = _normalize_search(query)
    if len(q) < 2:
        return []
    matches = []
    seen = set()

    # 1. ETF PEA matches (priorite 250)
    for tag, items in PEA_ETF_BOOST.items():
        ntag = _normalize_search(tag)
        if ntag in q or q in ntag:
            for sym, name in items:
                if sym in seen: continue
                seen.add(sym)
                matches.append({
                    "symbol":    sym, "shortname": name,
                    "exchange":  "Paris", "type": "ETF",
                    "peaScore":  250,
                })

    # 2. Actions CAC 40 / SBF 120 (priorite 200)
    for tag, (sym, name) in PEA_STOCK_INDEX.items():
        ntag = _normalize_search(tag)
        if ntag in q or q in ntag:
            if sym in seen: continue
            seen.add(sym)
            matches.append({
                "symbol":    sym, "shortname": name,
                "exchange":  "Paris", "type": "Action",
                "peaScore":  200,
            })

    return matches


def fetch_yahoo_search(query: str, limit: int = 6):
    """
    Recherche Yahoo orientee PEA : on demande beaucoup de resultats puis on
    priorise les bourses eligibles PEA (Paris d'abord, Euronext puis EU).
    On boost aussi les ETF PEA connus via un index local quand le terme matche.
    Renvoie au max `limit` resultats (defaut 6).
    Les resultats sont caches 5 minutes pour accelerer les recherches repetees.
    """
    if not query or len(query) < 1:
        return []

    # Cache de recherche (evite les appels Yahoo redondants)
    cache_key = _normalize_query(query)
    now = time.time()
    with _lock:
        cached = _search_cache.get(cache_key)
        if cached and (now - cached["ts"]) < SEARCH_CACHE_TTL:
            return cached["results"]

    try:
        url = (
            "https://query2.finance.yahoo.com/v1/finance/search"
            "?q=" + urllib.parse.quote(query)
            + "&quotesCount=25&newsCount=0&lang=fr-FR&region=FR"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())

        # Tableau de priorite par suffixe ticker (plus le score est haut, mieux c'est)
        # PEA eligibles : Euronext (Paris/Amsterdam/Bruxelles/Lisbonne) + Frankfurt + autres EU
        EXCHANGE_PRIORITY = {
            ".PA":  100,  # Paris -- la priorite absolue pour un PEA
            ".AS":   90,  # Amsterdam
            ".BR":   85,  # Bruxelles
            ".LS":   80,  # Lisbonne
            ".DE":   70,  # Xetra (Francfort)
            ".F":    60,  # Francfort
            ".MI":   55,  # Milan
            ".MC":   50,  # Madrid
            ".IR":   45,  # Dublin
            ".VI":   40,  # Vienne
            ".SW":   30,  # Suisse (NON-PEA mais EU proche)
            ".L":    20,  # Londres (NON-PEA depuis Brexit mais utile)
        }
        # Tout autre suffixe = score 0 (US, JP, HK, etc.)

        def score(sym: str) -> int:
            if not sym: return 0
            for suffix, sc in EXCHANGE_PRIORITY.items():
                if sym.endswith(suffix):
                    return sc
            # Pas de suffixe = tres probablement US
            return 0

        scored = []
        seen_names = set()  # evite les doublons par nom
        for q in data.get("quotes", []):
            sym = q.get("symbol")
            name = (q.get("shortname") or q.get("longname") or "").strip()
            if not sym or not name:
                continue
            key = (name.lower())  # un nom = un seul resultat (le mieux place)
            if key in seen_names:
                continue
            seen_names.add(key)

            s = score(sym)
            scored.append((s, {
                "symbol":    sym,
                "shortname": name,
                "exchange":  q.get("exchDisp") or q.get("exchange") or "",
                "type":      q.get("typeDisp") or q.get("quoteType") or "",
                "peaScore":  s,  # pour affichage UI eventuel
            }))

        # Tri par score decroissant
        scored.sort(key=lambda x: -x[0])
        yahoo_results = [item for _, item in scored]

        # Fusionne avec le boost local (ETF PEA connus en tete)
        local = _boost_local_etf(query)
        already_symbols = {r["symbol"] for r in local}
        for r in yahoo_results:
            if r["symbol"] in already_symbols:
                continue
            local.append(r)
            already_symbols.add(r["symbol"])

        results = local[:limit]
        with _lock:
            _search_cache[cache_key] = {"results": results, "ts": time.time()}
        return results
    except Exception as e:
        print(f"[server] search {query}: {e}", flush=True)
        # Si Yahoo plante, on renvoie quand meme l'index local s'il matche
        local_fallback = _boost_local_etf(query)[:limit]
        if local_fallback:
            with _lock:
                _search_cache[cache_key] = {"results": local_fallback, "ts": time.time()}
        return local_fallback


def fetch_yahoo_analysts(yahoo_ticker: str):
    """
    Recupere les avis analystes via le module quoteSummary de Yahoo.
    Retourne un dict avec : targetMean, targetHigh, targetLow, targetMedian,
    numAnalysts, recoMean (1=Strong Buy ... 5=Sell), recoKey (string).
    Renvoie None si indisponible (ex: ETF).
    """
    opener, crumb = _ensure_yahoo_session()
    if not opener or not crumb:
        return None

    for host in ("query1", "query2"):
        try:
            url = (
                f"https://{host}.finance.yahoo.com/v10/finance/quoteSummary/"
                + urllib.parse.quote(yahoo_ticker)
                + "?modules=financialData,recommendationTrend"
                + "&crumb=" + urllib.parse.quote(crumb)
            )
            with opener.open(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            result = data.get("quoteSummary", {}).get("result")
            if not result:
                continue

            fd = result[0].get("financialData", {}) or {}

            def _v(field):
                """Yahoo retourne souvent {raw: 12.34, fmt: '12.34', longFmt: ''}"""
                obj = fd.get(field)
                if isinstance(obj, dict):
                    return obj.get("raw")
                return obj

            target_mean   = _v("targetMeanPrice")
            target_high   = _v("targetHighPrice")
            target_low    = _v("targetLowPrice")
            target_median = _v("targetMedianPrice")
            num_analysts  = _v("numberOfAnalystOpinions")
            reco_mean     = _v("recommendationMean")
            reco_key      = fd.get("recommendationKey")

            # Si rien d'utile, on ne renvoie rien (ex: ETF)
            if not target_mean and not num_analysts:
                return None

            return {
                "targetMean":   target_mean,
                "targetHigh":   target_high,
                "targetLow":    target_low,
                "targetMedian": target_median,
                "numAnalysts":  num_analysts,
                "recoMean":     reco_mean,
                "recoKey":      reco_key,
            }
        except Exception as e:
            print(f"[server] analysts/{host} KO {yahoo_ticker}: {e}", flush=True)
            continue
    return None


def get_analysts(tickers):
    result, now = {}, time.time()
    for tk in tickers:
        ytk = to_yahoo(tk)
        with _lock:
            cached = _analysts_cache.get(ytk)
            if cached and (now - cached["ts"]) < ANALYSTS_CACHE_TTL:
                result[tk] = cached["data"]
                continue
        data = fetch_yahoo_analysts(ytk)
        if data is not None:
            with _lock:
                _analysts_cache[ytk] = {"data": data, "ts": now}
            result[tk] = data
    return result


# ─── Hydratation du cache depuis pea_data.json (mode hors-ligne) ─────────────

def hydrate_cache(prices_cache: dict, history_cache: dict) -> None:
    """Charge dans le cache memoire les valeurs venant du disque (au demarrage)."""
    now = time.time()
    with _lock:
        for tk, v in (prices_cache or {}).items():
            if isinstance(v, dict) and "cours" in v:
                # Format ancien tracker : {name, cours, w1, m1, y1}
                _cache[to_yahoo(tk)] = {
                    "prix": v.get("cours"),
                    "w1":   v.get("w1"),
                    "m1":   v.get("m1"),
                    "y1":   v.get("y1"),
                    "ts":   0,  # 0 force le refresh au prochain appel
                }
        for tk, v in (history_cache or {}).items():
            if isinstance(v, dict) and v.get("dates") and v.get("closes"):
                _history_cache[to_yahoo(tk)] = {
                    "dates": v["dates"],
                    "closes": v["closes"],
                    "ts": 0,
                }


def dump_cache() -> dict:
    """Renvoie le cache actuel pour le sauvegarder dans pea_data.json."""
    with _lock:
        return {
            "prices":  {k: dict(v) for k, v in _cache.items()},
            "history": {k: {"dates": v["dates"], "closes": v["closes"]} for k, v in _history_cache.items()},
        }


# ─── Handler HTTP ─────────────────────────────────────────────────────────────

class _Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # silence

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/ping":
            return self._json(200, {"ok": True, "time": int(time.time())})

        if parsed.path == "/cours":
            raw = params.get("tickers", [""])[0]
            if not raw.strip():
                return self._json(400, {"error": "Parametre tickers manquant"})
            tickers = [t.strip() for t in raw.split(",") if t.strip()]
            return self._json(200, {"ok": True, "prices": get_prices(tickers)})

        if parsed.path == "/history":
            raw = params.get("tickers", [""])[0]
            if not raw.strip():
                return self._json(400, {"error": "Parametre tickers manquant"})
            tickers = [t.strip() for t in raw.split(",") if t.strip()]
            range_p = (params.get("range", ["max"])[0] or "max").strip()
            # Whitelist
            if range_p not in {"1mo","3mo","6mo","ytd","1y","2y","5y","10y","max"}:
                range_p = "max"
            return self._json(200, {"ok": True, "history": get_history(tickers, range_param=range_p)})

        if parsed.path == "/analysts":
            raw = params.get("tickers", [""])[0]
            if not raw.strip():
                return self._json(400, {"error": "Parametre tickers manquant"})
            tickers = [t.strip() for t in raw.split(",") if t.strip()]
            return self._json(200, {"ok": True, "analysts": get_analysts(tickers)})

        if parsed.path == "/sparkline":
            raw = params.get("tickers", [""])[0]
            if not raw.strip():
                return self._json(400, {"error": "Parametre tickers manquant"})
            tickers = [t.strip() for t in raw.split(",") if t.strip()]
            return self._json(200, {"ok": True, "sparklines": get_sparklines(tickers)})

        if parsed.path == "/keystats":
            raw = params.get("tickers", [""])[0]
            if not raw.strip():
                return self._json(400, {"error": "Parametre tickers manquant"})
            tickers = [t.strip() for t in raw.split(",") if t.strip()]
            return self._json(200, {"ok": True, "keystats": get_keystats(tickers)})

        if parsed.path == "/search":
            q = params.get("q", [""])[0].strip()
            if len(q) < 1:
                return self._json(200, {"ok": True, "results": []})
            # local=1 : renvoie uniquement l'index local (instantane, sans appel Yahoo)
            if params.get("local", ["0"])[0] == "1":
                return self._json(200, {"ok": True, "results": _boost_local_etf(q)[:6]})
            return self._json(200, {"ok": True, "results": fetch_yahoo_search(q)})

        if parsed.path == "/profiles":
            try:
                import storage as _storage
                return self._json(200, {"ok": True, "state": _storage.get_profiles_state()})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        # ─── PIN endpoints (ultra-simples, fichier dedie) ─────────────────
        if parsed.path == "/pin/required":
            return self._json(200, {"ok": True, "required": pin_required()})

        if parsed.path == "/pin/set":
            pin = (params.get("pin", [""])[0] or "").strip()
            try:
                pin_set(pin)
                return self._json(200, {"ok": True, "required": pin_required()})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if parsed.path == "/pin/check":
            pin = (params.get("pin", [""])[0] or "").strip()
            return self._json(200, {"ok": True, "match": pin_check(pin)})

        if parsed.path == "/scan-orphan-data":
            try:
                import storage as _storage
                return self._json(200, {"ok": True, "candidates": _storage.scan_orphan_data()})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if parsed.path == "/recover-data":
            try:
                import storage as _storage
                src = (params.get("from", [""])[0] or "").strip()
                if not src:
                    return self._json(400, {"ok": False, "error": "from manquant"})
                stats = _storage.recover_from(src)
                return self._json(200, {"ok": True, "stats": stats})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})


        # Endpoint de fallback pour lire les donnees (utilise par l'UI au boot)
        if parsed.path == "/data":
            try:
                import storage as _storage
                data = _storage.load_data()
                load_info = _storage.get_last_load_info()
                debug = {
                    "data_path": str(_storage.get_data_path()),
                    "data_exists": _storage.get_data_path().exists(),
                    "data_size": _storage.get_data_path().stat().st_size if _storage.get_data_path().exists() else 0,
                    "appdata_env": os.environ.get("APPDATA", "(non defini)"),
                    "load_source": load_info.get("source", "?"),
                    "load_error":  load_info.get("error"),
                }
                return self._json(200, {"ok": True, "data": data, "_debug": debug})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        # Sert l'UI HTML embarquee (sans cache pour eviter les vieilles versions)
        if parsed.path in ("/", "/index.html") and _html_file_path:
            try:
                with open(_html_file_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(body)
                return
            except Exception as e:
                return self._json(500, {"error": f"HTML lecture KO : {e}"})

        self._json(404, {"error": "Not found"})

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


# ─── Demarrage / arret ────────────────────────────────────────────────────────

def _find_free_port(start: int = DEFAULT_PORT, attempts: int = 50) -> int:
    """Trouve le 1er port libre a partir de `start`."""
    for offset in range(attempts):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Aucun port libre entre {start} et {start + attempts}")


def start_server(html_path=None) -> int:
    """Demarre le serveur dans un thread daemon. Retourne le port utilise."""
    global _server_instance, _server_thread, _server_port, _html_file_path

    if html_path:
        _html_file_path = html_path

    if _server_instance is not None:
        return _server_port  # deja demarre

    _server_port = _find_free_port(DEFAULT_PORT)
    _server_instance = http.server.ThreadingHTTPServer((HOST, _server_port), _Handler)
    _server_thread = threading.Thread(
        target=_server_instance.serve_forever,
        name="CoursServer",
        daemon=True,  # important : meurt avec le process
    )
    _server_thread.start()
    print(f"[server] Demarre sur http://{HOST}:{_server_port}", flush=True)
    return _server_port


def stop_server() -> None:
    """Arrete proprement le serveur."""
    global _server_instance, _server_thread
    if _server_instance is None:
        return
    try:
        _server_instance.shutdown()
        _server_instance.server_close()
    except Exception:
        pass
    _server_instance = None
    _server_thread = None
    print("[server] Arrete.", flush=True)


def get_port() -> int:
    return _server_port
