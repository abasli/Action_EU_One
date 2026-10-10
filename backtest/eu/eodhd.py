"""Fournisseur de prix EOD Historical Data (eodhd.com) — Europe, radiés inclus.

Rôle
----
Remplace `tiingo.py` (source US) en exposant le MÊME contrat, pour que `signaux.py`
et `queues.py` tournent sans modification :
- `charger_panel(min_seances) -> DataFrame` long `[date, ticker, adj_close, close,
  volume, ...]`, avec `attrs["survivants_seulement"]` et `attrs["source"]` ;
- `RACINE`, et un cache de lots dans `data/eu/eodhd/`.

Endpoints EODHD (vérifiés sur la doc, 2026-10)
----------------------------------------------
- EOD      : GET /api/eod/{CODE.EXCH}?api_token=..&fmt=json&from=..&to=..&period=d&order=a
             -> [{date, open, high, low, close, adjusted_close, volume}, ...]
- Symboles : GET /api/exchange-symbol-list/{EXCH}?api_token=..&fmt=json&delisted=0|1 (cf. univers.py)
- Fondam.  : GET /api/fundamentals/{CODE.EXCH}?api_token=..&fmt=json
             -> General.CountryName/CountryISO, Highlights.MarketCapitalization
- Places   : GET /api/exchanges-list/?api_token=..  (pour CONFIRMER les codes de place)

Discipline anti-biais de survivance
-----------------------------------
Reprise du protocole de `tiingo.py` : `verifier_radies()` intercale des radiés EU
connus et des vivants dans la même session. Tant que ce test n'a pas confirmé que
EODHD sert bien les radiés (témoins vivants servis ET radiés servis), AUCUN chiffre
en aval n'est fiable — c'est le gate du projet.

Multi-devises — limite assumée (premier jet)
--------------------------------------------
Le STOXX 600 mêle EUR/GBP/CHF/… Les rendements `adjusted_close.pct_change()` sont des
rendements TOTAUX en devise LOCALE : corrects pour le classement transversal (le signal
est relatif), mais la P&L réelle d'un investisseur en euros porte aussi le change.
Le filtre de liquidité `dollar_vol` est lui aussi en devise locale ici. Conversion EUR
(via les séries FX EODHD) = raffinement à brancher avant toute conclusion sur le coût
mortel EN EUROS. À écrire noir sur blanc dans toute sortie.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
DOSSIER = RACINE / "data" / "eu" / "eodhd"
BASE = "https://eodhd.com/api"
DEBUT = "2007-01-01"


def token() -> str:
    """Lit le token depuis l'environnement ou le .env du dépôt (non versionné)."""
    t = os.environ.get("EODHD_TOKEN")
    if t:
        return t.strip()
    env = RACINE / ".env"
    if env.exists():
        for ligne in env.read_text().splitlines():
            if ligne.startswith("EODHD_TOKEN="):
                return ligne.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError(
        "EODHD_TOKEN introuvable. L'ajouter au .env du dépôt (déjà gitignoré) :\n"
        '  echo "EODHD_TOKEN=..." >> ' + str(env))


def _get(chemin: str, **params) -> tuple[int, object]:
    """Renvoie (code HTTP, corps décodé). Ne lève pas sur 4xx : on veut le code."""
    params.setdefault("fmt", "json")
    params["api_token"] = token()
    url = f"{BASE}{chemin}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "actions-eu/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            corps = r.read().decode()
            try:
                return r.status, json.loads(corps)
            except json.JSONDecodeError:
                return r.status, corps[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def exchanges_list() -> tuple[int, object]:
    """Liste des places et de leurs codes — pour CONFIRMER BOURSES_EU."""
    return _get("/exchanges-list/")


def eod(code: str, debut: str = DEBUT, fin: str | None = None) -> tuple[int, object]:
    p = {"from": debut, "period": "d", "order": "a"}
    if fin:
        p["to"] = fin
    return _get(f"/eod/{code}", **p)


def fondamentaux(code: str) -> tuple[int, object]:
    return _get(f"/fundamentals/{code}")


def barres(corps: object) -> tuple[list, str]:
    """Extrait les barres d'une réponse EOD, ou le warning EODHD le cas échéant.

    Sur abonnement gratuit, un radié — et toute demande au-delà d'un an — renvoie
    `[{"warning": "..."}]` au lieu des barres : on le capte au lieu de planter.
    """
    if isinstance(corps, list) and corps and isinstance(corps[0], dict):
        if "date" in corps[0]:
            return corps, ""
        if "warning" in corps[0]:
            return [], str(corps[0]["warning"])
    return [], ""


def capitalisations(codes: list[str]) -> dict[str, float | None]:
    """Capitalisation par code `CODE.EXCH`, en cache. None si indisponible.

    N'est appelé que sur les émetteurs FR (cf. couts.masque_taxable), donc le
    nombre de requêtes fondamentaux reste modeste.
    """
    DOSSIER.mkdir(parents=True, exist_ok=True)
    f = DOSSIER / "capi.json"
    cache = json.loads(f.read_text()) if f.exists() else {}
    reste = [c for c in codes if c not in cache]
    for i, c in enumerate(reste, 1):
        code, corps = fondamentaux(c)
        mc = None
        if code == 200 and isinstance(corps, dict):
            mc = (corps.get("Highlights") or {}).get("MarketCapitalization")
        cache[c] = float(mc) if mc else None
        if i % 25 == 0:
            print(f"  capi {i}/{len(reste)}", flush=True)
            f.write_text(json.dumps(cache))
        time.sleep(0.05)
    if reste:
        f.write_text(json.dumps(cache))
    return cache


# --------------------------------------------------------------------------
# normalisation et nettoyage
# --------------------------------------------------------------------------
def en_cadre(lignes: list[dict], info: dict) -> pd.DataFrame:
    """Normalise les barres EOD EODHD au schéma du projet.

    `close` reste BRUT (pour le filtre « prix > X »), `adj_close` = `adjusted_close`
    (pour rendements et amplitudes). `volume` EODHD est déjà ajusté des splits.
    """
    d = pd.DataFrame(lignes)
    if d.empty or "adjusted_close" not in d:
        return pd.DataFrame()
    d["date"] = pd.to_datetime(d["date"])
    out = pd.DataFrame({
        "date": d["date"],
        "ticker": info["ticker"],
        "symbole": info.get("Code"),
        "exchange": info.get("exch_req"),
        "isin": info.get("Isin"),
        "currency": info.get("Currency"),
        "open": d.get("open"), "high": d.get("high"), "low": d.get("low"),
        "close": d["close"], "adj_close": d["adjusted_close"],
        "volume": d["volume"],
    })
    return out.sort_values("date").reset_index(drop=True)


def tronquer_flatline(d: pd.DataFrame, min_suite: int = 3,
                      part_volume: float = 0.05) -> tuple[pd.DataFrame, int]:
    """Coupe la suite TERMINALE de séances au cours gelé (dernier cours recopié
    après une sortie de cote). Critère sur le PRIX, corroboré par l'effondrement
    du volume. Générique, repris tel quel de la chaîne US."""
    if len(d) < 2:
        return d, 0
    fige = d["close"].diff() == 0
    n = 0
    for i in range(len(d) - 1, 0, -1):
        if fige.iloc[i]:
            n += 1
        else:
            break
    if n < min_suite:
        return d, 0
    avant = d["volume"].iloc[max(0, len(d) - n - 60): len(d) - n]
    if len(avant) and avant.median() > 0:
        if d["volume"].iloc[-n:].median() > part_volume * avant.median():
            return d, 0
    return d.iloc[: len(d) - n], n


def decouper_trous(p: pd.DataFrame, jours_max: int = 180) -> pd.DataFrame:
    """Scinde une série partout où elle s'interrompt plus de `jours_max` jours
    (nouvelle société sous le même code, ou suspension longue). Générique."""
    p = p.sort_values(["ticker", "date"])
    trou = p.groupby("ticker")["date"].diff().dt.days > jours_max
    seg = trou.groupby(p["ticker"]).cumsum()
    multi = seg.groupby(p["ticker"]).transform("max") > 0
    p = p.copy()
    p.loc[multi, "ticker"] = (p.loc[multi, "ticker"] + "#"
                              + seg[multi].astype(int).astype(str))
    return p


# --------------------------------------------------------------------------
# collecte reprenable
# --------------------------------------------------------------------------
def _un_ticker(info: dict) -> tuple[str, object]:
    for essai in range(4):
        code, corps = eod(info["ticker"])
        if code == 429:
            time.sleep(2 ** essai * 3)
            continue
        bars, warn = barres(corps)
        if code != 200 or not bars:
            return info["ticker"], (warn[:40] or f"http_{code}")
        d = en_cadre(bars, info)
        if d.empty:
            return info["ticker"], "vide"
        d, _ = tronquer_flatline(d)
        return info["ticker"], d
    return info["ticker"], "http_429_persistant"


def collecter(annuaire: pd.DataFrame, par_lot: int = 300, fils: int = 8) -> None:
    """Charge l'EOD de tout l'annuaire, en cache par lots, reprenable.

    Une requête par cotation. Le manifeste n'est écrit qu'APRÈS le parquet, donc
    une interruption refait au pire un lot, jamais n'en perd un.
    """
    from concurrent.futures import ThreadPoolExecutor

    DOSSIER.mkdir(parents=True, exist_ok=True)
    manif = DOSSIER / "_traites.txt"
    echecs = DOSSIER / "_echecs.txt"
    faits = set(manif.read_text().split()) if manif.exists() else set()

    infos = [r._asdict() if hasattr(r, "_asdict") else dict(r)
             for _, r in annuaire.iterrows()]
    reste = [i for i in infos if i["ticker"] not in faits]
    print(f"{len(infos):,} cotations | {len(faits):,} en cache | "
          f"{len(reste):,} à faire | {fils} fils", flush=True)

    lots = [reste[i:i + par_lot] for i in range(0, len(reste), par_lot)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=fils) as ex:
        for n, lot in enumerate(lots, 1):
            res = list(ex.map(_un_ticker, lot))
            cadres = [d for _, d in res if isinstance(d, pd.DataFrame)]
            vides = [f"{t}\t{d}" for t, d in res if not isinstance(d, pd.DataFrame)]
            if cadres:
                pd.concat(cadres, ignore_index=True).to_parquet(
                    DOSSIER / f"lot_{n:04d}_{int(time.time())}.parquet", index=False)
            if vides:
                with echecs.open("a") as fh:
                    fh.write("\n".join(vides) + "\n")
            with manif.open("a") as fh:
                fh.write("\n".join(i["ticker"] for i in lot) + "\n")
            ecoule = time.time() - t0
            print(f"  lot {n:>3}/{len(lots)}  {len(vides):>4} sans données  "
                  f"reste ~{ecoule / n * (len(lots) - n) / 60:.0f} min", flush=True)


# Devises européennes converties en EUR (v2, extension largeur). USD/HKD exclus
# (cross-listings, pas des actions européennes). GBX = pence londonien = GBP/100.
TARGET_DEVISES = ("EUR", "GBX", "GBP", "CHF", "SEK", "DKK", "NOK")


def taux_change(devises, debut: str = DEBUT) -> pd.DataFrame:
    """Taux journaliers EUR par unité de devise (colonnes = devise, index = date).

    EUR = 1. GBX (pence) = taux GBP / 100. Source EODHD `/eod/{CUR}EUR.FOREX`.
    Sert à convertir PRIX et LIQUIDITÉ en EUR pour des filtres cohérents entre
    places ; les RENDEMENTS restent en devise locale (le signal est relatif).
    """
    via = {"GBX": "GBP"}
    cols = {}
    for dev in {d for d in devises if d != "EUR"}:
        c, corps = eod(f"{via.get(dev, dev)}EUR.FOREX", debut=debut)
        b, _ = barres(corps)
        if not b:
            print(f"  FX {dev}: indisponible (http={c}) — devise ignorée")
            continue
        s = pd.Series({pd.Timestamp(x["date"][:10]): float(x["close"]) for x in b})
        cols[dev] = s / 100.0 if dev == "GBX" else s
    fx = pd.DataFrame(cols).sort_index()
    fx["EUR"] = 1.0
    return fx


def charger_panel(min_seances: int = 500,
                  devises: tuple[str, ...] = TARGET_DEVISES) -> pd.DataFrame:
    """Recolle les lots en un panel long, biais de survivance traité + hygiène.

    Hygiène (motivée empiriquement) :
    - **prix strictement positifs** : un `adj_close`/`close` <= 0 fait exploser
      `pct_change` (rendements `inf` / milliards de %). ~6 000 cellules.
    - **conversion EUR** des prix et de la liquidité via `taux_change` (dont GBX
      pence → GBP/100) : rend le plancher de prix et le filtre de liquidité
      cohérents entre devises. Colonnes ajoutées `prix_eur`, `dvol_eur`.
      `adj_close` reste LOCAL → les rendements (le signal) sont des rendements
      totaux locaux ; la P&L réelle en euros porterait aussi le change (overlay
      FX, non modélisé ici — connu).
    - `devises` par défaut = zone euro + Londres/Suisse/Nordiques (GBX/GBP/CHF/
      SEK/DKK/NOK). Passer `("EUR",)` pour revenir à la v1 zone euro.
    """
    fichiers = sorted(DOSSIER.glob("lot_*.parquet"))
    if not fichiers:
        raise FileNotFoundError(f"aucun lot dans {DOSSIER} — lancer --charger")
    p = pd.concat([pd.read_parquet(f) for f in fichiers], ignore_index=True)
    p["date"] = pd.to_datetime(p["date"])
    p = p.dropna(subset=["adj_close"])
    p = p[p["currency"].isin(devises)]
    p = p[(p["adj_close"] > 0) & (p["close"] > 0)]

    # facteur EUR par (date, devise), FX reporté sur toutes les séances du panel
    fx = taux_change(devises)
    dates = pd.Index(sorted(p["date"].unique()))
    fx = fx.reindex(dates).ffill().bfill()
    fxl = fx.reset_index(names="date").melt(
        id_vars="date", var_name="currency", value_name="factor")
    p = p.merge(fxl, on=["date", "currency"], how="left").dropna(subset=["factor"])
    p["prix_eur"] = p["close"] * p["factor"]
    p["dvol_eur"] = p["prix_eur"] * p["volume"]

    p = p.drop_duplicates(["ticker", "date"])
    p = decouper_trous(p)
    p = p[p.groupby("ticker")["date"].transform("size") >= min_seances]
    p.attrs["survivants_seulement"] = False
    p.attrs["source"] = (f"eodhd (radiés servis, flatline tronquée, prix>0, "
                         f"EUR via FX, devises={'+'.join(devises)})")
    return p.sort_values(["ticker", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# LE test qui décide de tout — couverture des radiés
# --------------------------------------------------------------------------
# Radiations EU connues (code EODHD + date approx + note). CODES ET DATES À
# CONFIRMER au premier run : le test imprime http + nb de séances + fin réelle,
# donc une erreur de code se voit (http != 200) et ne passe pas pour une absence.
RADIES_EU = {
    "ALT.PA":  ("2020-04-01", "Altran -> Capgemini"),
    "ZC.PA":   ("2018-02-28", "Zodiac Aerospace -> Safran"),
    "ALU.PA":  ("2016-11-15", "Alcatel-Lucent -> Nokia"),
    "SEV.PA":  ("2022-07-18", "Suez -> Veolia (OPA)"),
    "ILD.PA":  ("2021-10-13", "Iliad -> retrait de cote"),
    "UG.PA":   ("2021-01-18", "Peugeot -> Stellantis"),
    "TEC.PA":  ("2017-01-17", "Technip -> TechnipFMC"),
}
# Témoins vivants : OBLIGATOIREMENT servis. S'ils échouent, le canal est en cause.
VIVANTS_EU = ["MC.PA", "OR.PA", "TTE.PA", "SAP.XETRA", "ASML.AS"]


def verifier_radies(pause: float = 0.8) -> pd.DataFrame:
    """Alterne radiés et vivants dans la même session, au même rythme."""
    sequence = []
    morts = list(RADIES_EU)
    for i, m in enumerate(morts):
        sequence.append((m, "radié"))
        if i < len(VIVANTS_EU):
            sequence.append((VIVANTS_EU[i], "vivant"))

    lignes = []
    for code, genre in sequence:
        c, corps = eod(code, debut="2005-01-01")
        bars, warn = barres(corps)
        n = len(bars)
        d1, d2 = (bars[0]["date"][:10], bars[-1]["date"][:10]) if n else ("", "")
        lignes.append({"code": code, "genre": genre, "http": c, "seances": n,
                       "debut": d1, "fin": d2, "warning": warn,
                       "note": RADIES_EU.get(code, ("", ""))[1]})
        suff = f"  !! {warn}" if warn else ""
        print(f"  {code:<10} {genre:<7} http={c:<4} {n:>6} séances  "
              f"{d1} -> {d2}{suff}", flush=True)
        time.sleep(pause)
    return pd.DataFrame(lignes)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--charger", action="store_true",
                   help="collecter l'EOD de tout l'annuaire (radiés compris)")
    a.add_argument("--places", action="store_true", help="lister les codes de place EODHD")
    a.add_argument("--fils", type=int, default=8)
    o = a.parse_args()

    print("=" * 78)
    print("EODHD — couverture EU et titres radiés")
    print("=" * 78)

    if o.places:
        code, corps = exchanges_list()
        print(f"http={code}")
        if isinstance(corps, list):
            for x in corps:
                print(f"  {x.get('Code'):<8} {x.get('Name')}  [{x.get('Country')}]")
        return

    if o.charger:
        import univers as U
        t = U.charger()
        print(f"{len(t):,} cotations à charger "
              f"({(~t['delisted']).sum():,} actives, {t['delisted'].sum():,} radiées)")
        collecter(t, fils=o.fils)
        return

    # gate par défaut : la couverture des radiés
    r = verifier_radies()
    print("\n" + "=" * 78)
    v, m = r[r["genre"] == "vivant"], r[r["genre"] == "radié"]
    ok_v, ok_m = (v["seances"] > 100).sum(), (m["seances"] > 100).sum()
    gratuit = r["warning"].str.contains("free subscription", case=False, na=False).any()
    sv = r.loc[r["seances"] > 0, "debut"]
    print(f"témoins vivants servis : {ok_v}/{len(v)}")
    print(f"radiés servis          : {ok_m}/{len(m)}")
    if len(sv):
        print(f"historique le plus ancien servi : {sv.min()}")
    if gratuit:
        print("\n!! ABONNEMENT GRATUIT détecté (warning EODHD) : historique borné à ~1 an")
        print("!! et radiés NON servis. Inexploitable pour un backtest long sans biais de")
        print("!! survivance. Il faut un plan payant (historique long + radiés). STOP.")
    elif ok_v < len(v):
        print("\n!! Des témoins VIVANTS échouent : canal/clé en cause. Ne rien conclure.")
    elif ok_m == 0:
        print("\n!! Canal sain, zéro radié servi : EODHD ne couvre pas les radiés EU ici. STOP.")
    else:
        print(f"\nCouverture des radiés CONFIRMÉE sur {ok_m} noms, canal sain.")
        print("Le biais de survivance devient corrigeable — collecte possible (--charger).")


if __name__ == "__main__":
    main()
