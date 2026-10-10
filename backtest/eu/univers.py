"""Univers d'actions européennes point-in-time, listées ET radiées (EODHD).

Pourquoi ce module
------------------
Même discipline que l'univers US : mesurer la population RÉELLE, radiés compris,
pas seulement les survivants. EODHD sert, pour chaque place, la liste des symboles
actifs (`delisted=0`) ET radiés (`delisted=1`) — ce dernier appel REMPLACE le jeu
de résultats, il faut donc appeler deux fois et fusionner sur `Code`.

Composition — limite assumée
-----------------------------
Il n'existe pas, gratuitement, de composition HISTORIQUE du STOXX 600 (appartenance
à l'indice date par date). Partir des constituants ACTUELS réintroduirait le biais
de survivance qu'on refuse. On prend donc un univers plus large et plus honnête :
toutes les **actions ordinaires** des grandes places européennes, listées et radiées.
La restriction « large/mid cap » est opérée en aval par le **filtre de liquidité**
(`dollar_vol` médian, cf. signaux/queues) et par la sélection en queue extrême — un
nom illiquide n'est jamais retenu. On approche ainsi « actions EU liquides » plutôt
que « STOXX 600 » stricto sensu ; à documenter dans toute conclusion.

Codes de place EODHD
--------------------
`BOURSES_EU` est une proposition à **confirmer** via `eodhd.exchanges_list()` : un code
erroné renvoie une erreur HTTP visible à la collecte (pas un silence). On ne devine pas.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from eodhd import _get, RACINE

CACHE = RACINE / "data" / "eu" / "annuaire"

# Places EU couvertes (codes EODHD présumés — à confirmer via exchanges_list()).
# PA Paris · XETRA Allemagne · AS Amsterdam · MI Milan · LSE Londres · BR Bruxelles
# LS Lisbonne · MC Madrid · SW Suisse (SIX) · ST Stockholm · CO Copenhague
# OL Oslo · HE Helsinki · VI Vienne · IR Dublin
BOURSES_EU = ["PA", "XETRA", "AS", "MI", "LSE", "BR", "LS", "MC", "SW",
              "ST", "CO", "OL", "HE", "VI", "IR"]

TYPES_ACTION = {"common stock", "stock"}
CHAMPS = ("Code", "Name", "Country", "Exchange", "Currency", "Type", "Isin")


def _liste(exch: str, delisted: bool) -> list[dict]:
    code, corps = _get(f"/exchange-symbol-list/{exch}",
                       delisted=1 if delisted else 0)
    if code != 200 or not isinstance(corps, list):
        print(f"  {exch:<6} delisted={int(delisted)} : http={code} — ignorée "
              f"({str(corps)[:80]})")
        return []
    return corps


def charger(bourses: list[str] | None = None, force: bool = False) -> pd.DataFrame:
    """Annuaire des actions ordinaires EU, une ligne par (Code, place).

    Identité stable = `ticker` = `CODE.EXCH` (le code EOD d'EODHD lui-même).
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / "annuaire_eu.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)

    bourses = bourses or BOURSES_EU
    lignes = []
    for exch in bourses:
        for dl in (False, True):
            for r in _liste(exch, dl):
                row = {k: r.get(k) for k in CHAMPS}
                row["exch_req"] = exch
                row["delisted"] = dl
                lignes.append(row)

    t = pd.DataFrame(lignes)
    if t.empty:
        raise RuntimeError("annuaire vide — vérifier la clé EODHD et les codes "
                           "de place (eodhd.exchanges_list()).")
    t["Type"] = t["Type"].fillna("").str.lower()
    t = t[t["Type"].isin(TYPES_ACTION)].copy()
    t["ticker"] = t["Code"].astype(str) + "." + t["exch_req"].astype(str)
    # un même Code peut apparaître actif ET radié : on garde une ligne, en
    # préférant la version qui porte un ISIN
    t = (t.sort_values("Isin", na_position="last")
           .drop_duplicates("ticker", keep="first")
           .reset_index(drop=True))
    t.to_parquet(f, index=False)
    return t


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="re-télécharger l'annuaire")
    p.add_argument("--bourses", nargs="+", help="sous-ensemble de places EODHD")
    a = p.parse_args()

    t = charger(a.bourses, a.force)
    print("=" * 76)
    print("UNIVERS ACTIONS EU POINT-IN-TIME (EODHD, radiés inclus)")
    print("=" * 76)
    print(f"{len(t):,} cotations  |  {t['exch_req'].nunique()} places")
    viv = (~t["delisted"]).sum()
    print(f"  actives {viv:,}  |  RADIÉES {len(t) - viv:,}  <- ce qui manquerait sans elles")
    print("répartition par place :", t["exch_req"].value_counts().to_dict())
    fr = t["Isin"].fillna("").str.upper().str.startswith("FR").sum()
    print(f"émetteurs français (ISIN FR, assiette TTF potentielle) : {fr:,}")
    print(f"\nannuaire -> {CACHE / 'annuaire_eu.parquet'}")


if __name__ == "__main__":
    main()
