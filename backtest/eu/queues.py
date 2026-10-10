"""Queue extrême : les N meilleurs contre les N pires, et non l'écart de déciles.

Pourquoi un module séparé de `signaux.py` alors que les signaux sont les mêmes.

L'écart de déciles répond à « ce signal classe-t-il correctement l'univers ? ».
C'est la bonne question pour un chercheur et la mauvaise pour nous : un décile
de cet univers, c'est 900 titres par jambe. Le robot ne peut en tenir que 10 à
30 en tout. On ne joue donc pas le décile supérieur (10 % de l'univers) mais la
queue extrême (0,15 %), qui est un objet statistique différent — plus bruité,
mais potentiellement bien plus chargé en signal.

Le portefeuille est modélisé tel qu'il serait tenu, pas tel qu'il se résume :

- **tranches chevauchantes.** Pour un horizon de h séances on ouvre chaque jour
  une tranche qui pèse 1/h du livre et on ferme celle de h jours. Le livre est
  donc toujours investi, et la série de rendements est QUOTIDIENNE — bien plus
  d'observations qu'un rebalancement tous les 5 jours, au prix d'une
  autocorrélation que Newey-West absorbe.
- **rotation exacte.** Comme toutes les lignes pèsent le même 1/(N*h), la
  variation de poids d'un jour est exactement (tranche entrante − tranche
  sortante)/h. Le notionnel échangé se calcule sur ces deux tranches seulement,
  sans approximation, et c'est lui qui paie le coût. Un titre reconduit d'une
  tranche à l'autre ne paie rien : c'est la différence entre coûter la rotation
  et coûter les signaux.
- **jambe courte restreinte.** Le découvert n'est pas disponible sur les
  petites valeurs, donc la vente à découvert est limitée à un seuil de
  liquidité plus sévère que l'achat. Les deux jambes n'ont pas le même univers.

Usage :
    python backtest/actions/queues.py                 # balayage complet
    python backtest/actions/queues.py --n 15 --h 10   # une configuration
"""
from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd

import signaux as S

warnings.filterwarnings("ignore")

# coût d'UNE jambe, en points de base du notionnel échangé. Le courtier n'est
# pas arrêté : on encadre, et on cherche surtout le coût mortel.
COUTS_PB = (0.0, 2.0, 5.0, 10.0)

# seuil de liquidité de la jambe courte, au-dessus du seuil d'achat : on ne vend
# pas à découvert ce qu'on ne peut pas emprunter. CONTRAINTE à re-mesurer en EUR
# (marché EU multi-devises ; le notionnel est à convertir en EUR, cf. eodhd.py).
DV_MIN_COURT = 1e7       # 10 M€/jour
PRIX_MIN_COURT = 5.0     # 5 €


# --------------------------------------------------------------------------
def masques(m: dict) -> tuple[np.ndarray, np.ndarray]:
    """Éligibilité à l'achat et, plus restrictive, à la vente à découvert."""
    achat = S.masque_liquidite(m)
    dv20 = m["dollar_vol"].rolling(20, min_periods=15).median()
    court = achat & (m["close"] > PRIX_MIN_COURT) & (dv20 > DV_MIN_COURT)
    return achat.to_numpy(), court.to_numpy()


def selectionner(sig: np.ndarray, el_long: np.ndarray, el_court: np.ndarray,
                 n: int) -> tuple[np.ndarray, np.ndarray]:
    """Indices des n plus forts (achetables) et des n plus faibles (vendables).

    Renvoie -1 dans les cases non pourvues : un jour où moins de n titres sont
    éligibles ne doit pas être silencieusement complété par des titres interdits.
    """
    d, k = sig.shape
    hauts = np.full((d, n), -1, dtype=np.int32)
    bas = np.full((d, n), -1, dtype=np.int32)

    for j in range(d):
        s = sig[j]
        ok = np.isfinite(s)
        vl, vc = ok & el_long[j], ok & el_court[j]
        if vl.sum() < 50 or vc.sum() < 50:
            continue                       # univers trop mince, journée ignorée
        il, ic = np.flatnonzero(vl), np.flatnonzero(vc)
        nl, nc = min(n, len(il)), min(n, len(ic))
        hauts[j, :nl] = il[np.argsort(-s[il], kind="stable")[:nl]]
        bas[j, :nc] = ic[np.argsort(s[ic], kind="stable")[:nc]]
    return hauts, bas


def poids_tranche(idx: np.ndarray, pond: np.ndarray | None,
                  d: np.ndarray) -> np.ndarray:
    """Poids des lignes d'une tranche, somme 1 par jambe.

    `pond=None` donne l'équipondération. Sinon on normalise la pondération
    fournie sur les seules cases pourvues — un jour où la jambe n'a que 3 noms
    sur 5 doit rester investi à 100 %, pas à 60 %.
    """
    pourvu = idx[d] >= 0
    w = np.where(pourvu, 1.0 if pond is None
                 else np.take_along_axis(pond[d], np.clip(idx[d], 0, None), axis=1),
                 0.0)
    w = np.where(np.isfinite(w), w, 0.0)
    s = w.sum(axis=1, keepdims=True)
    return np.divide(w, s, out=np.zeros_like(w), where=s > 0)


def portefeuille(hauts: np.ndarray, bas: np.ndarray, rdt: np.ndarray,
                 h: int, par_jambe: bool = False,
                 pond: np.ndarray | None = None, delai: int = 1,
                 pas: int = 1, reequilibrage: bool = True,
                 taxable: np.ndarray | None = None):
    """Série quotidienne du rendement brut et du notionnel échangé.

    `pas` est l'intervalle entre deux OUVERTURES de tranche, et c'est lui qui
    fixe la taille réelle du livre. À `pas=1` on ouvre tous les jours, donc on
    porte h tranches de 2n lignes en même temps : 300 positions pour n=10,
    h=15. C'est le réglage mesuré, et il est hors de la contrainte « 10 à 30
    lignes » ([[project-actions-contraintes-execution]]). À `pas=h` on n'a
    qu'une tranche vivante, donc 2n lignes, mais on perd le moyennage qui
    lissait la série. Le nombre de tranches concurrentes est h/pas, et le
    nombre de lignes 2*n*h/pas.

    `delai=1` est la convention de `signaux.py` : signal connu au close de d,
    position ouverte au close de d+1, donc on ne négocie jamais au cours qui a
    servi à décider. C'est prudent et, pour un signal de retournement, c'est
    peut-être trop cher : le rebond qu'on achète peut se produire pendant la
    séance qu'on passe à attendre.

    `delai=0` entre au close de d. Ce n'est PAS de l'anticipation si le signal
    est recalculé quelques minutes avant la cloche et envoyé en « market on
    close » — c'est un ordre que le courtier accepte. Ce n'en est une que si on
    prétend décider sur le cours de clôture définitif puis l'obtenir. L'écart
    entre les deux versions mesure donc une borne haute de ce que l'exécution
    MOC peut récupérer, et non un gain acquis.

    `reequilibrage` corrige une incohérence du modèle d'origine, qui facturait
    un livre figé tout en encaissant le rendement d'un livre rééquilibré. Les
    poids d'une tranche (`W[d]`) sont en effet RÉAPPLIQUÉS à chaque séance de
    sa vie : le rendement calculé est donc celui d'un portefeuille ramené
    chaque jour à l'équipondération, ce qui exige de vendre les lignes qui
    montent et de racheter celles qui baissent. Cette rotation-là n'était pas
    comptée, et elle n'est pas anecdotique sur une queue extrême peuplée des
    titres les plus agités. À `False` on retrouve les chiffres d'avant.
    """
    if h % pas:
        raise ValueError(f"h={h} doit être un multiple de pas={pas}")
    nt = h // pas                          # tranches vivantes simultanément
    nd = rdt.shape[0]
    echange = np.zeros(nd)
    # notionnel d'ACQUISITION sur noms taxables à la TTF française, mêmes unités
    # que `echange` (fraction du livre). La TTF est asymétrique : elle frappe les
    # achats (position nette acheteuse du jour), pas la rotation symétrique.
    achat_tax = np.zeros(nd)
    valide = (hauts[:, 0] >= 0) & (bas[:, 0] >= 0)
    tous = np.arange(nd)
    WL, WC = poids_tranche(hauts, pond, tous), poids_tranche(bas, pond, tous)

    # contribution d'une tranche décidée en d, k séances après son ouverture
    trl = np.full((nd, h + 1), np.nan)     # jambe longue seule
    trc = np.full((nd, h + 1), np.nan)     # jambe courte seule (rendement du titre)
    tre = np.full((nd, h + 1), np.nan)     # rotation de rééquilibrage, 2 jambes
    for k in range(1, h + 1):
        src = tous + delai + k
        d = np.flatnonzero((src < nd) & valide)
        if len(d) == 0:
            continue
        r = rdt[src[d]]
        tre[d, k] = 0.0
        for idx, W, cible in ((hauts, WL, trl), (bas, WC, trc)):
            v = np.take_along_axis(r, np.clip(idx[d], 0, None), axis=1)
            # une ligne sans cotation ce jour-là est redistribuée sur les
            # autres, et non comptée pour un rendement nul
            w = np.where(np.isfinite(v), W[d], 0.0)
            s = w.sum(axis=1, keepdims=True)
            w = np.divide(w, s, out=np.zeros_like(w), where=s > 0)
            rp = (np.nan_to_num(v) * w).sum(axis=1)
            cible[d, k] = np.where(s[:, 0] > 0, rp, np.nan)

            # Ramener la jambe à ses poids cibles après le mouvement du jour.
            # Le poids dérivé de la ligne i vaut w_i(1+v_i)/(1+rp), donc le
            # notionnel à échanger est somme |w_i(1+v_i)/(1+rp) - w_i|, soit
            # somme w_i|v_i - rp|/(1+rp). C'est exact, pas une approximation :
            # c'est la définition même du rééquilibrage que le rendement
            # ci-dessus suppose déjà fait.
            ecart = np.abs(np.nan_to_num(v) - rp[:, None]) * w
            tre[d, k] += np.where(s[:, 0] > 0,
                                  ecart.sum(axis=1) / (1.0 + rp), 0.0)

        # même motif de NaN que le rendement, sinon `empiler` ne compterait pas
        # les mêmes tranches des deux côtés et la rotation serait sous-estimée
        tre[d, k] = np.where(np.isfinite(trl[d, k]) & np.isfinite(trc[d, k]),
                             tre[d, k], np.nan)

    # le livre du jour j est la moyenne des nt tranches encore vivantes, soit
    # celles ouvertes en j-delai-k pour les k dont le jour d'ouverture tombe
    # sur la grille de pas
    def empiler(tr):
        cumul, compte = np.zeros(nd), np.zeros(nd)
        for k in range(1, h + 1):
            src = np.arange(nd) - delai - k
            j = np.flatnonzero((src >= 0) & (src % pas == 0))
            c = tr[src[j], k]
            cumul[j] += np.nan_to_num(c)
            compte[j] += np.isfinite(c)
        # un jour où une tranche manquait reste NaN et ne vaut pas 0
        return np.where(compte == nt, cumul / nt, np.nan)

    rl, rc = empiler(trl), empiler(trc)
    brut = rl - rc

    # rotation : (tranche entrante − tranche sortante) / nt, exactement.
    # Rien ne bouge les jours hors grille : le livre est figé entre deux
    # ouvertures, et c'est là que `pas` fait baisser le coût.
    for j in range(h + delai, nd):
        a, b = j - delai, j - delai - h
        if a % pas or not (valide[a] and valide[b]):
            continue
        poids: dict[int, float] = {}
        for idx, W, signe in ((hauts, WL, +1.0), (bas, WC, -1.0)):
            for c, i in enumerate(idx[a]):
                if i >= 0:
                    poids[i] = poids.get(i, 0.0) + signe * W[a, c]
            for c, i in enumerate(idx[b]):
                if i >= 0:
                    poids[i] = poids.get(i, 0.0) - signe * W[b, c]
        echange[j] = sum(abs(v) for v in poids.values()) / nt
        if taxable is not None:
            # assiette TTF = part POSITIVE du changement de position sur un nom
            # taxable (achat long ou rachat de couverture d'un short), à
            # l'ouverture seulement. La TTF du rééquilibrage quotidien est une
            # raffinement laissé de côté dans ce premier jet.
            achat_tax[j] = sum(v for i, v in poids.items()
                               if v > 0 and taxable[i]) / nt

    # après la boucle : celle-ci AFFECTE echange[j], elle ne l'accumule pas
    if reequilibrage:
        echange += np.nan_to_num(empiler(tre))

    if par_jambe:
        return brut, echange, rl, rc, achat_tax
    return brut, echange, achat_tax


def z(sig: pd.DataFrame, elig: np.ndarray) -> np.ndarray:
    """Rang transversal ramené à [-1, 1], parmi les seuls éligibles.

    Le rang plutôt que le z-score brut : `choc_volume` est un ratio à queue
    droite épaisse, sa moyenne et son écart-type transversaux sont dominés par
    quelques valeurs et un z-score les laisserait écraser les autres signaux
    dans le composite.
    """
    v = sig.to_numpy().copy()
    v[~elig] = np.nan
    r = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
    return 2 * r - 1


def mesurer(nom: str, brut: np.ndarray, echange: np.ndarray,
            dates: pd.DatetimeIndex, h: int, n: int,
            ttf_jour: np.ndarray | None = None) -> list[dict]:
    """Rendement annualisé et t de Newey-West pour chaque hypothèse de coût.

    `ttf_jour` (coût TTF quotidien, taux déjà appliqué) n'est PAS une hypothèse :
    la TTF s'applique toujours, on la retranche du brut dans tous les cas. `pb`
    encadre, lui, le spread/commission de la rotation symétrique, encore inconnu
    tant que le courtier n'est pas choisi. Le coût mortel se lit donc « pb/jambe
    qui annule le gain, TTF déjà payée ».
    """
    ok = np.isfinite(brut)
    if ok.sum() < 250:
        return []
    ttf = np.zeros_like(brut) if ttf_jour is None else ttf_jour
    out = []
    for pb in COUTS_PB:
        net = pd.Series((brut - ttf)[ok] - echange[ok] * pb / 1e4, index=dates[ok])
        moy, t, nn = S.t_newey_west(net, h)
        sd = net.std()
        out.append({"signal": nom, "h": h, "n_lignes": 2 * n, "pb": pb,
                    "jours": nn, "annuel_pct": moy * 252 * 100, "t_nw": t,
                    "sharpe": moy / sd * np.sqrt(252) if sd > 0 else np.nan,
                    "rotation_j": echange[ok].mean(),
                    "ttf_pct_an": ttf[ok].mean() * 252 * 100})
    return out


def cout_mortel(lignes: list[dict]) -> float:
    """Coût par jambe qui annule exactement le gain, par interpolation linéaire.

    Le rendement net est affine en pb (le coût est proportionnel au notionnel
    échangé, lui-même indépendant du coût), donc l'extrapolation est exacte et
    pas une approximation : brut / (rotation * 252) * 1e4.
    """
    b = next(x for x in lignes if x["pb"] == 0)
    if b["annuel_pct"] <= 0 or b["rotation_j"] <= 0:
        return 0.0
    return b["annuel_pct"] / 100 / (b["rotation_j"] * 252) * 1e4


SOUS_PERIODES = (("2009-2013", "2009", "2013"), ("2014-2018", "2014", "2018"),
                 ("2019-2022", "2019", "2022"), ("2023-2026", "2023", "2026"),
                 ("hors 2009", "2010", "2026"), ("depuis 2014", "2014", "2026"))


def marche(m: dict, elig: np.ndarray, rogne: float = 0.01) -> np.ndarray:
    """Rendement de marché en moyenne élaguée, sous masque d'éligibilité.

    L'élagage n'est pas une coquetterie : `adjClose` ne répercute pas certains
    regroupements d'actions, et trois lignes à +100 000 % suffisent à porter la
    moyenne brute du panel à +3 % par jour.
    """
    r = np.where(elig, m["rdt"].to_numpy(), np.nan)
    out = np.full(len(r), np.nan)
    for j in range(len(r)):
        v = r[j][np.isfinite(r[j])]
        if len(v) < 20:
            continue
        b = np.quantile(v, [rogne, 1 - rogne])
        out[j] = v[(v >= b[0]) & (v <= b[1])].mean()
    return out


def ligne(nom: str, x: pd.Series, h: int, pb: float = 0.0,
          ech: pd.Series | None = None) -> None:
    net = x if ech is None else x - ech * pb / 1e4
    net = net.dropna()
    moy, t, n = S.t_newey_west(net, h)
    sd = net.std()
    sh = moy / sd * np.sqrt(252) if sd > 0 else np.nan
    print(f"  {nom:<26}{n:>7}{moy * 252 * 100:>10.1f}%{t:>8.2f}{sh:>9.2f}")


def inverse_vol(m: dict) -> np.ndarray:
    """1 / volatilité réalisée à 20 jours, connue au close de la décision.

    La queue extrême d'un signal de retournement est peuplée des titres les
    plus agités : à l'équipondération, deux ou trois lignes font toute la
    variance du livre. Égaliser le risque et non le capital est le levier
    évident sur le Sharpe, et il ne coûte rien de plus en rotation.
    """
    v = m["rdt"].rolling(20, min_periods=15).std().to_numpy()
    return np.where(v > 0, 1.0 / v, np.nan)


def bootstrap(x: pd.Series, bloc: int = 21, tirages: int = 5000,
              graine: int = 0) -> float:
    """p unilatéral par rééchantillonnage en blocs, sans hypothèse de normalité.

    Le t de Newey-West suppose que la moyenne de la série est à peu près
    gaussienne. Avec 2 lignes par jambe, une séance du livre est le rendement
    de quatre titres : la distribution est très asymétrique et à queues
    épaisses, exactement le cas où un t de 3 peut n'être qu'un artefact. Les
    blocs de 21 séances préservent l'autocorrélation que les tranches
    chevauchantes introduisent.
    """
    v = x.to_numpy()
    n = len(v)
    nb = n // bloc
    if nb < 10:
        return np.nan
    centre = v - v.mean()                 # hypothèse nulle : moyenne vraie nulle
    r = np.random.default_rng(graine)
    deb = r.integers(0, n - bloc, size=(tirages, nb))
    ech = centre[(deb[:, :, None] + np.arange(bloc)).reshape(tirages, -1)]
    return float((ech.mean(axis=1) >= v.mean()).mean())


def valider(nom_sig: str, sigs: dict, m: dict, el_long: np.ndarray,
            el_court: np.ndarray, n: int, h: int,
            pond: np.ndarray | None = None, delai: int = 1,
            pas: int = 1, taxable: np.ndarray | None = None) -> None:
    """Ce qui décide vraiment : la stabilité dans le temps et l'origine du gain."""
    rdt = m["rdt"].to_numpy()
    dates = m["rdt"].index
    sv = sigs[nom_sig].to_numpy()
    mkt = marche(m, el_long)

    hauts, bas = selectionner(sv, el_long, el_court, n)
    brut, ech, rl, rc, achat_tax = portefeuille(hauts, bas, rdt, h, par_jambe=True,
                                                pond=pond, delai=delai, pas=pas,
                                                taxable=taxable)
    b = pd.Series(brut, index=dates)
    e = pd.Series(ech, index=dates)
    tf = pd.Series(K.TTF_TAUX * achat_tax, index=dates)   # coût TTF quotidien

    print(f"\n{'=' * 70}\n{nom_sig} | {n} par jambe | h={h} | pas={pas}"
          f" | {2 * n * h // pas} lignes tenues\n{'=' * 70}")
    print(f"  {'découpe':<26}{'jours':>7}{'/an':>11}{'t NW':>8}{'Sharpe':>9}")

    print("\n-- sous-périodes, brut")
    for lbl, a, z_ in SOUS_PERIODES:
        ligne(lbl, b.loc[a:z_], h)

    print("\n-- sous-périodes, net TTF + 5 pb/jambe")
    for lbl, a, z_ in SOUS_PERIODES:
        ligne(lbl, (b - tf).loc[a:z_], h, 5.0, e.loc[a:z_])

    print("\n-- d'où vient le gain (jambes couvertes du marché)")
    ligne("jambe longue - marché", pd.Series(rl - mkt, index=dates), h)
    ligne("marché - jambe courte", pd.Series(mkt - rc, index=dates), h)

    print("\n-- années")
    an = b.groupby(b.index.year).agg(["sum", "count"])
    pos = (an["sum"] > 0).sum()
    print(f"  {pos}/{len(an)} années positives  |  "
          f"pire {an['sum'].min() * 100:.1f}%  meilleure {an['sum'].max() * 100:.1f}%")

    print("\n-- ce que le t gaussien ne dit pas (net TTF + 5 pb/jambe)")
    net = (b - tf - e * 5.0 / 1e4).dropna()
    print(f"  coût TTF française (toujours payé)     {tf.mean() * 252 * 100:>9.1f} %/an")
    cum = net.cumsum()
    sans10 = (net.sum() - net.nlargest(10).sum()) / net.sum() * 100
    print(f"  perte maximale depuis un sommet   {(cum - cum.cummax()).min() * 100:>9.1f}%")
    print(f"  pire séance / meilleure séance    {net.min() * 100:>9.1f}%"
          f" / {net.max() * 100:.1f}%")
    print(f"  gain restant sans les 10 meilleurs jours {sans10:>8.0f}%")
    print(f"  p bootstrap par blocs de 21 jours {bootstrap(net):>10.4f}")


# --------------------------------------------------------------------------
def main() -> None:
    a = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--n", type=int, nargs="+", default=[5, 15],
                   help="lignes par jambe (le total tenu est le double)")
    a.add_argument("--h", type=int, nargs="+", default=[5, 10, 15],
                   help="horizon de détention en séances")
    a.add_argument("--min-seances", type=int, default=1000)
    a.add_argument("--valider", metavar="SIGNAL",
                   help="sous-périodes et décomposition par jambe d'un seul signal")
    a.add_argument("--liquide-partout", action="store_true",
                   help="appliquer aussi à l'achat le seuil de liquidité du découvert")
    a.add_argument("--delai", type=int, default=1, choices=[0, 1],
                   help="séances entre la décision et l'entrée (0 = MOC)")
    a.add_argument("--pas", type=int, nargs="+", default=[1],
                   help="séances entre deux ouvertures de tranche ; "
                        "le livre tient 2*n*h/pas lignes")
    a.add_argument("--signaux", nargs="+", help="ne tester que ces signaux")
    a.add_argument("--inverse-vol", action="store_true",
                   help="pondérer par le risque plutôt que par le capital")
    o = a.parse_args()

    import eodhd as SRC
    import couts as K
    panel = SRC.charger_panel(min_seances=o.min_seances)
    m = S.en_matrices(panel)
    # masque des noms soumis à la TTF française (émetteur FR via ISIN + capi
    # > 1 Md€), aligné sur les colonnes du panel. Construit une fois.
    meta = panel.drop_duplicates("ticker").set_index("ticker")
    taxable = K.masque_taxable(list(m["rdt"].columns), meta, SRC)
    el_long, el_court = masques(m)
    if o.liquide_partout:
        # la queue extrême d'un univers semi-liquide peut n'être qu'un
        # artefact de cotation ; ce test le dit
        el_long = el_court
    rdt = m["rdt"].to_numpy()
    dates = m["rdt"].index
    sigs = S.construire_signaux(m)

    cadre = dict(index=m["rdt"].index, columns=m["rdt"].columns)

    # composite : moyenne des rangs, après avoir orienté chaque signal dans le
    # sens de sa jambe longue (c'est déjà la convention de construire_signaux)
    sigs["composite"] = pd.DataFrame(
        np.nanmean([z(s, el_long) for s in sigs.values()], axis=0), **cadre)

    # famille du retournement. `mom_3_1` ressort fortement NÉGATIF dans la
    # queue extrême : acheter le gagnant à 3 mois perd. Retourné, il dit
    # exactement ce que dit `reversal_21j` à un mois. Les deux signaux sont
    # arrivés séparément à la même conclusion économique, ce qui est la seule
    # raison acceptable de les combiner — pas leur t.
    sigs["rev_famille"] = pd.DataFrame(
        np.nanmean([z(sigs["reversal_21j"], el_long),
                    z(-sigs["mom_3_1"], el_long)], axis=0), **cadre)

    print(f"\npanel : {panel['ticker'].nunique():,} titres  "
          f"{dates.min().date()} -> {dates.max().date()}")
    print(f"achetables en médiane : {int(el_long.sum(axis=1)[252:].mean()):,}/jour  |  "
          f"vendables à découvert : {int(el_court.sum(axis=1)[252:].mean()):,}/jour")
    print(f"tranches chevauchantes, coût sur rotation exacte, t Newey-West\n")

    pond = inverse_vol(m) if o.inverse_vol else None
    if o.valider:
        if o.valider not in sigs:
            raise SystemExit(f"signal inconnu : {o.valider}  ({', '.join(sigs)})")
        valider(o.valider, sigs, m, el_long, el_court, o.n[0], o.h[0],
                pond, o.delai, o.pas[0], taxable)
        return

    if o.signaux:
        inconnus = set(o.signaux) - set(sigs)
        if inconnus:
            raise SystemExit(f"signal inconnu : {', '.join(inconnus)}")
        sigs = {k: v for k, v in sigs.items() if k in o.signaux}

    res = []
    for nom, s in sigs.items():
        sv = s.to_numpy()
        for n in o.n:
            hauts, bas = selectionner(sv, el_long, el_court, n)
            for h in o.h:
                for pas in o.pas:
                    if h % pas:
                        continue
                    brut, echange, achat_tax = portefeuille(
                        hauts, bas, rdt, h, pond=pond, delai=o.delai,
                        pas=pas, taxable=taxable)
                    ttf_jour = K.TTF_TAUX * achat_tax
                    lignes = mesurer(nom, brut, echange, dates, h, n, ttf_jour)
                    if lignes:
                        mortel = cout_mortel(lignes)
                        for x in lignes:
                            x["mortel_pb"] = mortel
                            x["pas"] = pas
                            x["n_lignes"] = 2 * n * h // pas
                        res.extend(lignes)

    r = pd.DataFrame(res)
    if r.empty:
        print("aucune configuration mesurable")
        return

    print("=" * 100)
    print("QUEUE EXTRÊME  —  N lignes par jambe   (seuil de conviction : |t| > 3)")
    print("=" * 100)
    print(f"{'signal':<16}{'h':>3}{'pas':>4}{'lignes':>7}{'rotat/j':>9}"
          f"{'netTTF/an':>11}{'t':>7}{'TTF/an':>8}{'net 2pb':>9}{'t 2pb':>7}"
          f"{'net 10pb':>10}{'mortel pb':>11}")

    cle = r[r["pb"] == 0].sort_values("t_nw", ascending=False)
    for b in cle.itertuples():
        g = r[(r["signal"] == b.signal) & (r["h"] == b.h)
              & (r["pas"] == b.pas)
              & (r["n_lignes"] == b.n_lignes)].set_index("pb")
        marque = "  <<<" if g.loc[2.0, "t_nw"] > 3 else ""
        print(f"{b.signal:<16}{b.h:>3}{b.pas:>4}{b.n_lignes:>7}{b.rotation_j:>9.1%}"
              f"{b.annuel_pct:>11.1f}{b.t_nw:>7.2f}{b.ttf_pct_an:>8.1f}"
              f"{g.loc[2.0, 'annuel_pct']:>9.1f}{g.loc[2.0, 't_nw']:>7.2f}"
              f"{g.loc[10.0, 'annuel_pct']:>10.1f}{b.mortel_pb:>11.1f}{marque}")

    print("\nlecture : 'netTTF/an' est déjà NET de la TTF française (colonne 'TTF/an'),")
    print("mais BRUT de spread/commission. 'mortel pb' est le coût par jambe qui ramène")
    print("alors le gain à zéro — le chiffre qui décide tant que le courtier n'est pas")
    print("choisi : en dessous de ~5 pb/jambe, aucune exécution retail ne tient.")

    (SRC.RACINE / "data" / "eu").mkdir(parents=True, exist_ok=True)
    r.to_csv(SRC.RACINE / "data" / "eu" / "queues.csv", index=False)
    print(f"\ndétail -> data/eu/queues.csv")


if __name__ == "__main__":
    main()
