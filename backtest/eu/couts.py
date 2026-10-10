"""Coûts spécifiques au marché européen — la TTF française.

Pourquoi un module à part
-------------------------
Le coût mortel du projet US était symétrique : un coût en pb appliqué au notionnel
ÉCHANGÉ (les deux jambes). La taxe française sur les transactions financières (TTF)
ne l'est pas : elle frappe **l'acquisition** de titres de sociétés françaises de
grande capitalisation, à l'achat seulement, à 0,30 % du montant acquis (art. 235 ter
ZD du CGI, décret depuis 2012, taux porté à 0,30 % en 2017).

Pour une stratégie à forte rotation, c'est potentiellement mortel : chaque entrée
longue sur une large-cap française paie 30 pb, à comparer au coût mortel US de
45 pb/jambe. Elle doit donc être **modélisée dans le coût mortel, pas supposée**.

Assiette retenue (premier jet)
------------------------------
`queues.portefeuille` calcule, à chaque ouverture de tranche, la part POSITIVE du
changement de position par nom taxable (achat long ou rachat de couverture d'un
short) — c'est l'assiette de la TTF. Ce module fournit le TAUX et le MASQUE des
noms taxables ; `queues.mesurer` retranche `TTF_TAUX × assiette` du brut, toujours.

Un nom est taxable si :
- l'émetteur est **français** — approché par le préfixe **ISIN « FR »**, qui suit la
  nationalité de l'émetteur et non la place de cotation (une société française
  cotée à Amsterdam reste taxable ; une non-française cotée à Paris ne l'est pas) ;
- **et** sa capitalisation dépasse **1 Md€** (seuil légal), lu dans les fondamentaux
  EODHD. Capitalisation inconnue → on taxe par prudence (borne haute du coût).

Limites assumées, à raffiner :
- la TTF du rééquilibrage quotidien n'est pas comptée (seulement les ouvertures) ;
- le seuil 1 Md€ est appliqué sur la capi COURANTE, pas point-in-time ;
- la liste nominative des sociétés taxables publiée annuellement (Bulletin officiel)
  serait plus exacte que ISIN+capi — à brancher si le premier chiffre est limite.
"""
from __future__ import annotations

import numpy as np

# Taux de la TTF française, sur le montant acquis.
TTF_TAUX = 0.0030

# Seuil légal de capitalisation (sociétés dont le siège est en France).
SEUIL_CAPI_EUR = 1e9


def _code(ticker: str) -> str:
    """Code EODHD d'un ticker de panel, suffixe de découpe de trou retiré."""
    return str(ticker).split("#", 1)[0]


def masque_taxable(tickers: list[str], meta, source=None) -> np.ndarray:
    """Masque booléen des noms soumis à la TTF, aligné sur `tickers`.

    `meta` : DataFrame indexé par ticker de panel, colonne `isin` (et le ticker
    sert de code EODHD `CODE.EXCHANGE`). `source` : module eodhd, pour lire la
    capitalisation des seuls noms FR (économise les appels). Sans `source`, tous
    les noms FR sont réputés taxables (borne haute).
    """
    def isin(t: str) -> str:
        if t in meta.index and "isin" in meta.columns:
            v = meta.at[t, "isin"]
            return str(v).upper() if v is not None else ""
        return ""

    fr = np.array([isin(t).startswith("FR") for t in tickers])

    capi: dict[str, float | None] = {}
    if source is not None and fr.any():
        codes = sorted({_code(t) for t, f in zip(tickers, fr) if f})
        try:
            capi = source.capitalisations(codes)
        except Exception as e:                       # réseau/clé absents : prudent
            print(f"  couts: capitalisations indisponibles ({e}) — noms FR tous taxés")
            capi = {}

    taxable = np.zeros(len(tickers), bool)
    for i, (t, f) in enumerate(zip(tickers, fr)):
        if not f:
            continue
        c = capi.get(_code(t))
        taxable[i] = (c is None) or (c > SEUIL_CAPI_EUR)
    n_fr, n_tax = int(fr.sum()), int(taxable.sum())
    print(f"  TTF : {n_fr} noms FR (ISIN) dont {n_tax} taxables (> 1 Md€) "
          f"sur {len(tickers)} du panel")
    return taxable
