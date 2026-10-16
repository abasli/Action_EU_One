"""Un stop sur la ligne vaut-il quelque chose ? Contre-épreuve européenne.

Mesuré sur le panel US le 2026-10-16 (`Actions_US_One`,
`backtest/actions/sortie_stop.py`) : un stop à 20 % de perte sur la ligne
affiche +3,9 points de rendement annuel, pour un **t d'écart apparié de
0,89** contre un seuil de 3, un balayage non monotone et un écart positif
seulement 9 années sur 18. Autrement dit un creux de bruit, selon toute
vraisemblance — mais « selon toute vraisemblance » n'est pas une mesure.

Ce fichier est la contre-épreuve sur un autre échantillon.

CE QU'IL FAUT SAVOIR AVANT DE LIRE LE RÉSULTAT, ET QUI LIMITE SA PORTÉE.

1. **`reversal_21j` est MORT en Europe** : −21,9 %/an, t = −1,40
   (`data/eu/queues.csv`, verdict du 2026-10-10, n=15 h=15 pas=5). La
   question mesurée ici n'est donc pas « le stop améliore-t-il la stratégie »
   mais « le stop réduit-il une perte ». C'est informatif sur le MÉCANISME —
   si couper les lignes qui vont fort contre nous apporte quelque chose, ça
   doit se voir aussi sur un livre perdant — mais ce n'est pas le même test
   que sur le panel US.

2. **Le calendrier est le même.** Le gain du stop aux États-Unis est
   concentré sur 2020, 2021 et 2026. L'Europe traverse les mêmes chocs
   mondiaux aux mêmes dates : un gain qui réapparaîtrait en 2020 ici ne
   serait pas une réplication indépendante, juste le même krach vu d'un autre
   continent. Seule la DIMENSION TRANSVERSALE est neuve, pas la temporelle.

3. **L'échantillon est court** : 1 128 séances de livre valide contre 4 192
   aux États-Unis. L'erreur-type de l'écart sera à l'avenant.

4. **La TTF des sorties en cours de tranche n'est pas comptée.** La base ne
   taxe que les acquisitions à l'ouverture (caveat assumé de `couts.py`), et
   un rachat de couverture déclenché par un stop est une acquisition
   taxable. Ne pas la compter **flatte le stop** : tout résultat positif
   d'ici est donc une borne haute.

Le témoin sans stop doit reproduire `queues.portefeuille` à l'identique —
c'est ce que vérifie `--verifier`, et le script refuse de continuer sinon.

    venv/bin/python backtest/eu/sortie_stop.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import couts as K                                              # noqa: E402
import queues as Q                                             # noqa: E402
import signaux as S                                            # noqa: E402

SIGNAL = "reversal_21j"
# n=5 est le réglage du verdict EU figé. Piège de lecture : la colonne
# `n_lignes` de `data/eu/queues.csv` n'est pas 2n mais la TAILLE DU LIVRE,
# `2*n*h//pas` (écrasée dans `queues.main`), donc 30 lignes = n=5.
N, H, PAS, DELAI = 5, 15, 5, 1
COUT_PB = 5.0
STOPS = (None, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0)


def portefeuille_stop(hauts, bas, rdt, h, stop, delai=1, pas=1,
                      taxable=None):
    """`queues.portefeuille` avec une sortie sur perte de ligne.

    Portage direct de `Actions_US_One/backtest/actions/sortie_stop.py`, avec
    la TTF du projet EU. Copie délibérée plutôt que modification de
    `queues.py` : une sortie conditionnelle casse l'hypothèse sur laquelle sa
    boucle est bâtie (toute tranche vit h).

    Les trois décisions de modélisation sont celles du fichier US : le poids
    libéré part en CASH et n'est pas redistribué ; la sortie paie sa rotation
    au poids d'après mouvement et le jour de grille ne décompte que les
    lignes encore vivantes ; déclenchement au close, vente au close suivant.
    """
    if h % pas:
        raise ValueError(f"h={h} doit être un multiple de pas={pas}")
    nt = h // pas
    nd = rdt.shape[0]
    n = hauts.shape[1]
    echange = np.zeros(nd)
    achat_tax = np.zeros(nd)
    valide = (hauts[:, 0] >= 0) & (bas[:, 0] >= 0)
    tous = np.arange(nd)
    WL, WC = Q.poids_tranche(hauts, None, tous), Q.poids_tranche(bas, None, tous)

    trl = np.full((nd, h + 1), np.nan)
    trc = np.full((nd, h + 1), np.nan)
    tre = np.full((nd, h + 1), np.nan)
    survL = np.ones((nd, n), dtype=bool)
    survC = np.ones((nd, n), dtype=bool)
    etat = {nom: {"cum": np.zeros((nd, n)),
                  "t1": np.zeros((nd, n), dtype=bool),
                  "t2": np.zeros((nd, n), dtype=bool)} for nom in ("L", "C")}

    for k in range(1, h + 1):
        src = tous + delai + k
        d = np.flatnonzero((src < nd) & valide)
        if len(d) == 0:
            continue
        r = rdt[src[d]]
        tre[d, k] = 0.0
        for nom, idx, W, cible, signe in (("L", hauts, WL, trl, +1.0),
                                          ("C", bas, WC, trc, -1.0)):
            e = etat[nom]
            v = np.take_along_axis(r, np.clip(idx[d], 0, None), axis=1)
            w = np.where(np.isfinite(v), W[d], 0.0)
            s = w.sum(axis=1, keepdims=True)
            w = np.divide(w, s, out=np.zeros_like(w), where=s > 0)
            vivante = ~e["t2"][d]
            w = np.where(vivante, w, 0.0)          # le poids libéré va en cash
            rp = (np.nan_to_num(v) * w).sum(axis=1)
            cible[d, k] = np.where(s[:, 0] > 0, rp, np.nan)

            vendue = e["t1"][d] & ~e["t2"][d]
            ecart = np.abs(np.nan_to_num(v) - rp[:, None]) * w * ~vendue
            ferme = w * (1.0 + np.nan_to_num(v)) / (1.0 + rp)[:, None] * vendue
            tre[d, k] += np.where(
                s[:, 0] > 0,
                ecart.sum(axis=1) / (1.0 + rp) + ferme.sum(axis=1), 0.0)

            if stop is not None:
                c = (1.0 + e["cum"][d]) * (1.0 + np.nan_to_num(v)) - 1.0
                e["cum"][d] = np.where(vivante, c, e["cum"][d])
                perte = -signe * e["cum"][d]
                e["t2"][d] = e["t1"][d]
                e["t1"][d] = e["t1"][d] | (vivante & (perte <= -stop / 100.0))
            if k == h:
                (survL if nom == "L" else survC)[d] = ~e["t2"][d]

        tre[d, k] = np.where(np.isfinite(trl[d, k]) & np.isfinite(trc[d, k]),
                             tre[d, k], np.nan)

    def empiler(tr):
        cumul, compte = np.zeros(nd), np.zeros(nd)
        for k in range(1, h + 1):
            s_ = np.arange(nd) - delai - k
            j = np.flatnonzero((s_ >= 0) & (s_ % pas == 0))
            c = tr[s_[j], k]
            cumul[j] += np.nan_to_num(c)
            compte[j] += np.isfinite(c)
        return np.where(compte == nt, cumul / nt, np.nan)

    rl, rc = empiler(trl), empiler(trc)
    brut = rl - rc

    for j in range(h + delai, nd):
        a, b = j - delai, j - delai - h
        if a % pas or not (valide[a] and valide[b]):
            continue
        poids: dict[int, float] = {}
        for idx, W, surv, signe in ((hauts, WL, survL, +1.0),
                                    (bas, WC, survC, -1.0)):
            for c, i in enumerate(idx[a]):
                if i >= 0:
                    poids[i] = poids.get(i, 0.0) + signe * W[a, c]
            for c, i in enumerate(idx[b]):
                if i >= 0 and surv[b, c]:
                    poids[i] = poids.get(i, 0.0) - signe * W[b, c]
        echange[j] = sum(abs(x) for x in poids.values()) / nt
        if taxable is not None:
            # assiette TTF = part positive du changement de position sur un
            # nom taxable, à l'ouverture seulement — comme la base. Les
            # rachats déclenchés en cours de tranche ne sont donc pas taxés,
            # ce qui FLATTE le stop (voir l'en-tête, point 4).
            achat_tax[j] = sum(x for i, x in poids.items()
                               if x > 0 and taxable[i]) / nt

    echange += np.nan_to_num(empiler(tre))
    return brut, echange, achat_tax


def main() -> None:
    a = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--stops", type=float, nargs="+")
    a.add_argument("--n", type=int, default=N,
                   help="lignes par jambe (5 = le réglage du verdict figé)")
    a.add_argument("--min-seances", type=int, default=1000)
    a.add_argument("--liquide-partout", action="store_true")
    a.add_argument("--annees", action="store_true")
    o = a.parse_args()

    stops = STOPS if not o.stops else (None, *o.stops)

    t0 = time.time()
    import eodhd as SRC
    panel = SRC.charger_panel(min_seances=o.min_seances)
    m = S.en_matrices(panel)
    meta = panel.drop_duplicates("ticker").set_index("ticker")
    taxable = K.masque_taxable(list(m["rdt"].columns), meta, SRC)
    el_long, el_court = Q.masques(m)
    if o.liquide_partout:
        el_long = el_court
    rdt = m["rdt"].to_numpy()
    dates = m["rdt"].index
    sig = S.construire_signaux(m)[SIGNAL].to_numpy()
    print(f"\npanel chargé en {time.time() - t0:.0f} s")

    n = o.n
    hauts, bas = Q.selectionner(sig, el_long, el_court, n)

    # --------------------------------------------------- contrôle du témoin
    b0, e0, a0 = Q.portefeuille(hauts, bas, rdt, H, pond=None, delai=DELAI,
                                pas=PAS, taxable=taxable)
    b1, e1, a1 = portefeuille_stop(hauts, bas, rdt, H, None, delai=DELAI,
                                   pas=PAS, taxable=taxable)
    print("\n--- contrôle du témoin contre queues.py ---")
    ok = True
    for nom, x, y in (("brut", b0, b1), ("echange", e0, e1), ("ttf", a0, a1)):
        meme = np.array_equal(np.isfinite(x), np.isfinite(y))
        msk = np.isfinite(x) & np.isfinite(y)
        ec = float(np.abs(x[msk] - y[msk]).max()) if msk.any() else np.inf
        bon = meme and ec < 1e-12
        ok &= bon
        print(f"  {nom:<8} NaN identiques {str(meme):<5} écart max {ec:.2e}"
              f"  {'OK' if bon else 'ÉCHEC'}")
    if not ok:
        raise SystemExit("\nLe témoin ne reproduit pas queues.py : "
                         "rien d'autre n'est lisible.")

    ref = Q.mesurer(SIGNAL, b0, e0, dates, H, n, K.TTF_TAUX * a0)
    r0 = next(x for x in ref if x["pb"] == 0)
    print(f"  témoin brut {r0['annuel_pct']:+.1f} %/an  t {r0['t_nw']:+.2f}  "
          f"{r0['jours']} jours\n  (référence figée du 2026-10-10 : "
          f"-21,9 %/an, t -1,40, 1 128 jours)")

    # ------------------------------------------------------------- balayage
    nets = {}
    print(f"\n{'stop':>7}{'jours':>7}{'brut%':>8}{'net%':>8}{'t':>7}"
          f"{'rot%':>7}{'TTF%':>7}{'écart':>8}{'t écart':>9}")
    print("-" * 68)
    for st in stops:
        brut, ech, atx = portefeuille_stop(hauts, bas, rdt, H, st,
                                           delai=DELAI, pas=PAS,
                                           taxable=taxable)
        ttf = K.TTF_TAUX * atx
        lignes = Q.mesurer("x", brut, ech, dates, H, n, ttf)
        if not lignes:
            print(f"{str(st):>7}  série trop courte")
            continue
        x0 = next(x for x in lignes if x["pb"] == 0)
        x5 = next(x for x in lignes if x["pb"] == COUT_PB)
        nets[st] = pd.Series(brut - ttf - ech * COUT_PB / 1e4,
                             index=dates).dropna()
        if st is None:
            ec, td = 0.0, np.nan
        else:
            d = (nets[st] - nets[None]).dropna()
            _, td, _ = S.t_newey_west(d, H)
            ec = (nets[st].mean() - nets[None].mean()) * 252 * 100
        nom = "aucun" if st is None else f"{st:g} %"
        print(f"{nom:>7}{x5['jours']:>7}{x0['annuel_pct']:>7.1f}%"
              f"{x5['annuel_pct']:>7.1f}%{x5['t_nw']:>7.2f}"
              f"{x0['rotation_j'] * 100:>6.1f}%{x0['ttf_pct_an']:>6.2f}%"
              f"{ec:>+8.1f}{td:>9.2f}")

    print("\nRappel : la base perd 22 %/an ici, donc un « écart positif » "
          "veut dire\n« perd moins », pas « gagne ». Et le seuil du projet "
          "reste |t| > 3.")

    if o.annees and None in nets:
        print(f"\n{'année':<8}" + "".join(f"{f'{s:g}%' if s else 'témoin':>10}"
                                          for s in stops))
        for an in range(dates[0].year, dates[-1].year + 1):
            x = [nets[s].loc[f"{an}":f"{an}-12-31"] for s in stops if s in nets]
            if len(x[0]) < 100:
                continue
            print(f"{an:<8}" + "".join(f"{v.mean() * 252 * 100:>+9.1f}%"
                                       for v in x))


if __name__ == "__main__":
    main()
