"""Mesure transversale de signaux swing sur actions US (5 à 15 séances).

AVERTISSEMENT DE BIAIS — ce module tourne aujourd'hui sur un ÉCHAFAUDAGE
------------------------------------------------------------------------
Le panel vient de `prix.py`, donc de Yahoo, qui ne sert aucun titre radié.
47 % de la population de 2011 est absente. Aucun chiffre produit ici n'est
une conclusion tant que `panel.attrs["survivants_seulement"]` vaut True ; le
module le vérifie et refuse de se taire là-dessus. L'objet est de déboguer la
chaîne pour que l'arrivée des prix radiés soit une réexécution.

Protocole de mesure
-------------------
1. SANS ANTICIPATION. Le signal est calculé sur les données closes en t.
   L'entrée se fait au close de t+1, la sortie au close de t+1+h. On ne peut
   pas négocier au close qui sert à décider : le décalage d'une séance est le
   minimum honnête.

2. FENÊTRES CHEVAUCHANTES. À h > 1, mesurer chaque jour donne des rendements
   qui se recouvrent, ce qui gonfle le t brut d'environ racine(h). On corrige
   par Newey-West (noyau de Bartlett, lag = h) — sinon on lit un t de 6 là où
   il n'y a qu'un t de 2.

3. FILTRE DE LIQUIDITÉ point-in-time. Prix > 5 $ et volume en dollars médian
   sur 20 séances > 5 M$, évalués en t. Sans cela le décile extrême se remplit
   de micro-capitalisations dont on ne peut rien tirer et dont le coût de
   transaction dépasse le signal.

4. PORTE DE COÛT (convention du projet) : coût aller-retour rapporté au
   mouvement typique sur l'horizon. Au-delà de 20 % le signal est hostile,
   au-delà de 40 % il est mort. Mesuré ici sur la rotation réelle du panier,
   pas sur une hypothèse de rotation intégrale.

Le seuil de conviction du projet reste |t| > 3, pas 2.
"""

from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Hypothèses de coût, ASSUMÉES et non mesurées. Corwin-Schultz a été essayé et
# rejeté : il rend 0,0 pb médian sur SPY parce que plus de la moitié des
# estimations journalières sortent négatives et sont écrêtées. L'estimateur
# décroche aux niveaux de liquidité des grandes capitalisations. On encadre
# donc plutôt que de prétendre mesurer.
COUT_ALLER_RETOUR_PB = {"optimiste": 2.0, "prudent": 10.0}

HORIZONS = (5, 10, 15)
N_DECILES = 10


# --------------------------------------------------------------------------
# mise en forme
# --------------------------------------------------------------------------
def en_matrices(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Passe du panel long à des matrices date x ticker (le format de travail)."""
    m = {}
    for col in ("adj_close", "close", "volume"):
        m[col] = panel.pivot(index="date", columns="ticker", values=col).sort_index()
    m["rdt"] = m["adj_close"].pct_change()
    # Garde-fou données (EU) : un rendement journalier > 100 % sur une large/mid
    # cap est quasi toujours une erreur de tick ou d'ajustement (reverse split,
    # prix corrompu). On le neutralise en NaN (donc exclu, PAS compté comme 0) —
    # sinon la queue extrême, qui sélectionne justement les plus gros mouvements,
    # se remplit de ces aberrations. Les prix <= 0 sont déjà écartés en amont.
    m["rdt"] = m["rdt"].where(m["rdt"].abs() <= 1.0)
    m["dollar_vol"] = m["close"] * m["volume"]
    return m


def masque_liquidite(m: dict, prix_min: float = 5.0,
                     dv_min: float = 5e6) -> pd.DataFrame:
    """Éligibilité en t, à partir d'informations connues en t. Pas d'anticipation."""
    dv20 = m["dollar_vol"].rolling(20, min_periods=15).median()
    return (m["close"] > prix_min) & (dv20 > dv_min)


# --------------------------------------------------------------------------
# signaux — tous calculés sur des données closes en t
# --------------------------------------------------------------------------
def construire_signaux(m: dict) -> dict[str, pd.DataFrame]:
    """Les candidats classiques à l'horizon swing.

    Convention de SIGNE : chaque signal est orienté pour qu'une valeur haute
    soit la jambe longue attendue. `reversal_5j` est donc l'opposé du rendement
    récent — on achète ce qui a baissé.
    """
    c = m["adj_close"]
    r = m["rdt"]
    s = {}

    # momentum : le décalage d'un mois (skip) évite de mélanger momentum et
    # retournement court, qui ont des signes opposés sur ces horizons
    s["mom_12_1"] = c.shift(21) / c.shift(252) - 1
    s["mom_6_1"] = c.shift(21) / c.shift(126) - 1
    s["mom_3_1"] = c.shift(21) / c.shift(63) - 1

    # retournement court terme : la jambe longue est la perdante récente
    s["reversal_5j"] = -(c / c.shift(5) - 1)
    s["reversal_21j"] = -(c / c.shift(21) - 1)

    # volatilité : anomalie de basse volatilité, la jambe longue est la calme
    s["basse_vol_20j"] = -r.rolling(20, min_periods=15).std()
    s["basse_vol_60j"] = -r.rolling(60, min_periods=45).std()

    # position dans le canal 52 semaines
    haut = c.rolling(252, min_periods=200).max()
    bas = c.rolling(252, min_periods=200).min()
    s["proche_du_haut"] = (c - bas) / (haut - bas)

    # accélération du volume : intérêt inhabituel
    dv = m["dollar_vol"]
    s["choc_volume"] = (dv.rolling(5, min_periods=4).mean()
                        / dv.rolling(60, min_periods=45).mean())

    return s


def rendement_futur(m: dict, h: int) -> pd.DataFrame:
    """Rendement d'une position ouverte au close de t+1 et fermée au close de t+1+h.

    Indexé sur t, la date de DÉCISION. Le décalage d'une séance est ce qui
    interdit de négocier au close qui a servi à décider.
    """
    c = m["adj_close"]
    return (c.shift(-(1 + h)) / c.shift(-1) - 1)


# --------------------------------------------------------------------------
# statistique
# --------------------------------------------------------------------------
def t_newey_west(x: pd.Series, lag: int) -> tuple[float, float, int]:
    """Moyenne, t corrigé de l'autocorrélation (Bartlett), nombre d'observations.

    Sans cette correction, des fenêtres qui se chevauchent sur h séances
    donnent un t gonflé d'environ racine(h) : un signal nul paraît significatif.
    """
    x = pd.Series(x).dropna()
    n = len(x)
    if n < 30:
        return np.nan, np.nan, n
    e = x.values - x.values.mean()
    gamma0 = (e @ e) / n
    var = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        gk = (e[k:] @ e[:-k]) / n
        var += 2 * (1 - k / (lag + 1)) * gk
    if var <= 0:
        return x.mean(), np.nan, n
    return x.mean(), x.mean() / np.sqrt(var / n), n


def deciles(sig_t: pd.Series, eligibles: pd.Series) -> pd.Series:
    """Rang transversal en déciles parmi les seuls titres éligibles en t."""
    v = sig_t[eligibles & sig_t.notna()]
    if len(v) < 50:                      # sous 50 noms les déciles sont du bruit
        return pd.Series(dtype=float)
    return pd.qcut(v.rank(method="first"), N_DECILES, labels=False, duplicates="drop")


# --------------------------------------------------------------------------
# évaluation d'un signal
# --------------------------------------------------------------------------
def evaluer(nom: str, sig: pd.DataFrame, m: dict, elig: pd.DataFrame,
            h: int, pas: int = 5) -> dict:
    """Écart décile haut moins décile bas, rebalancé tous les `pas` jours.

    `pas` réduit le chevauchement sans l'éliminer ; Newey-West s'occupe du reste.
    """
    dates = sig.index[252:-(h + 2)][::pas]
    ecarts, rotations, n_noms = [], [], []
    panier_prec = None

    fut = rendement_futur(m, h)

    for d in dates:
        dec = deciles(sig.loc[d], elig.loc[d])
        if dec.empty:
            continue
        haut = dec[dec == dec.max()].index
        bas = dec[dec == 0].index
        rh, rb = fut.loc[d, haut].mean(), fut.loc[d, bas].mean()
        if pd.isna(rh) or pd.isna(rb):
            continue
        ecarts.append(rh - rb)
        n_noms.append(len(haut) + len(bas))

        panier = set(haut) | set(bas)
        if panier_prec is not None:
            # part du panier renouvelée : c'est elle qui paie le coût
            rotations.append(len(panier - panier_prec) / max(len(panier), 1))
        panier_prec = panier

    if len(ecarts) < 30:
        return {"signal": nom, "h": h, "n": len(ecarts)}

    e = pd.Series(ecarts)
    # lag NW en nombre de rebalancements couverts par l'horizon
    lag = max(int(np.ceil(h / pas)), 1)
    moy, t, n = t_newey_west(e, lag)
    rot = float(np.mean(rotations)) if rotations else 1.0

    # porte de coût : le coût paie les deux jambes, pondéré par la rotation
    mouvement = abs(moy)
    res = {"signal": nom, "h": h, "n": n, "ecart_moy_pct": moy * 100,
           "t_nw": t, "t_brut": moy / (e.std() / np.sqrt(n)),
           "rotation": rot, "noms_moy": float(np.mean(n_noms))}
    for lbl, pb in COUT_ALLER_RETOUR_PB.items():
        cout = 2 * (pb / 1e4) * rot        # deux jambes
        res[f"cout_{lbl}_pct_du_signal"] = (cout / mouvement * 100
                                            if mouvement > 0 else np.inf)
        res[f"net_{lbl}_pct"] = (moy - cout) * 100
    return res


# --------------------------------------------------------------------------
def main() -> None:
    a = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--pas", type=int, default=5, help="jours entre rebalancements")
    a.add_argument("--min-seances", type=int, default=1000)
    o = a.parse_args()

    import eodhd as SRC
    panel = SRC.charger_panel(min_seances=o.min_seances)

    if panel.attrs.get("survivants_seulement"):
        print("!" * 74)
        print("! ÉCHAFAUDAGE — panel de SURVIVANTS. 47 % de la population manque.")
        print("! Les chiffres ci-dessous servent à déboguer la mesure, PAS à conclure.")
        print("! Source :", panel.attrs.get("source"))
        print("!" * 74)

    m = en_matrices(panel)
    elig = masque_liquidite(m)
    sigs = construire_signaux(m)

    print(f"\npanel : {panel['ticker'].nunique():,} titres  "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()}")
    print(f"éligibles en médiane : {int(elig.sum(axis=1).median()):,} titres/jour")
    print(f"signaux testés : {len(sigs)}  |  horizons : {HORIZONS} séances")
    print(f"rebalancement tous les {o.pas} jours, t corrigé Newey-West\n")

    lignes = []
    for nom, s in sigs.items():
        for h in HORIZONS:
            lignes.append(evaluer(nom, s, m, elig, h, o.pas))

    r = pd.DataFrame(lignes).dropna(subset=["t_nw"])
    r = r.sort_values("t_nw", key=abs, ascending=False)

    print("=" * 96)
    print("ÉCART DÉCILE HAUT - DÉCILE BAS   (seuil de conviction du projet : |t| > 3)")
    print("=" * 96)
    print(f"{'signal':<16}{'h':>3}{'n':>6}{'écart %':>9}{'t brut':>8}{'t NW':>7}"
          f"{'rotat.':>8}{'coût/sig 10pb':>14}{'net 10pb %':>12}")
    for x in r.itertuples():
        marque = "  <<<" if abs(x.t_nw) > 3 else ""
        print(f"{x.signal:<16}{x.h:>3}{x.n:>6}{x.ecart_moy_pct:>9.2f}"
              f"{x.t_brut:>8.2f}{x.t_nw:>7.2f}{x.rotation:>8.0%}"
              f"{x.cout_prudent_pct_du_signal:>13.0f}%{x.net_prudent_pct:>12.2f}{marque}")

    print("\nlecture : 'coût/sig' est la porte de coût du projet — au-delà de 20 %")
    print("le signal est hostile, au-delà de 40 % il est mort. 'net' retire le coût.")
    print("'t brut' vs 't NW' montre ce que le chevauchement des fenêtres gonflait.")

    if panel.attrs.get("survivants_seulement"):
        print("\n" + "!" * 74)
        print("! Rappel : biais de survivance non corrigé. Rien ci-dessus n'est établi.")
        print("!" * 74)


if __name__ == "__main__":
    main()
