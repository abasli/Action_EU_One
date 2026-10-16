# Résultats — backtest actions EU (verdict 2026-10-10)

## Verdict : NO-GO. L'edge extrême-queue US ne se transpose pas en Europe.

Testé proprement (panel EODHD radiés inclus, 2007→2026, données nettoyées, TTF française
modélisée, t de Newey-West, bootstrap par blocs). Conclusion robuste, confirmée sur
**3 signaux × 2 tailles d'univers**.

### Univers testés
| v | périmètre | éligibles/jour | titres |
|---|---|---|---|
| v1 | zone euro (EUR seul) | ~255 | 4 208 |
| v2 | + Londres/Suisse/Nordiques, normalisé EUR via FX | ~482 | 9 707 |

(US de référence : ~1 729 éligibles/jour.)

### Ce qui a été mesuré (queue extrême n=5, h=15, pas=5, net TTF+coûts)
- **`reversal_21j`** (le signal US) : **mort** en EU — net ~0 à négatif, t ≤ 0,2 (v1), −1,4 (v2).
  La jambe longue (acheter les perdants) perd : en Europe le court terme est momentum, pas reversal.
- **`reversal_5j`** : t global 2,4-2,7 mais **mirage** — tout l'edge est pré-2019 ; 2019-2022 ≈ 0,
  2023-2026 **négatif**. Short-only.
- **`proche_du_haut`** (meilleur) : t global ~2,5-2,6, **jamais > 3**. Significatif **uniquement
  pré-2019** ; 2019-2022 t≈0,6 (non sig.) ; **2023-2026 ≈ 0 (t≈0)**. Short-only (long t≈−2, short t≈+4,6).

### Pourquoi c'est un NON
1. **Aucun signal ne franchit la barre du projet |t| > 3** en out-of-sample.
2. **Décroissance post-2019** systématique : tout l'edge est concentré 2009-2018, nul à négatif depuis.
   Doubler l'univers (v1→v2) n'a changé ni le t global ni cette décroissance.
3. **Edge à une seule jambe** (le short des retardataires/gagnants) — le plus cher et le plus
   dur à exécuter en EUR (emprunt, restrictions de vente à découvert, le PEA ne shorte pas).

### Limites connues (ne changent pas le verdict)
- Rendements en devise locale (overlay FX non modélisé) — correct pour un test de SIGNAL.
- Italie absente (EODHD : volume=0 + pas de radiés sur `cboe.eodhd.com`).
- TTF modélisée sur les ouvertures de tranche (pas le rééquilibrage) — mineur (0,7-1,3 %/an).

### Valeur de l'exercice
Obtenu pour ~20 € (un mois EODHD Historian) et quelques heures, **sans construire de robot live**.
Le process « backtest d'abord, barre |t|>3, coût mortel » a fait exactement son travail : dire non vite.

---

## Contre-épreuve rendue au projet US : le stop sur la ligne (2026-10-16)

Le panel EU a servi une deuxième fois, pour une question qui n'est pas la sienne.

Côté US (`Actions_US_One`), un **stop à 20 % de perte sur la ligne** affichait
+3,9 points de rendement annuel — pour un t d'écart apparié de 0,89 contre un seuil
de 3, et un balayage non monotone. Donc probablement un creux de bruit, mais il
fallait un autre échantillon pour le dire. Mesuré ici par **`backtest/eu/sortie_stop.py`**
aux conventions du verdict — **n=5** h=15 pas=5 delai=1, net 5 pb/jambe, TTF payée.

| stop | 10 % | 15 % | 20 % | 25 % | 30 % | 40 % |
|---|---|---|---|---|---|---|
| écart vs témoin (pt/an) | **+1,4** | −4,0 | **−6,9** | −8,6 | −9,6 | −9,5 |
| t de l'écart | 0,20 | −0,64 | −1,26 | −1,77 | −2,16 | −2,20 |

**Cinq stops sur six aggravent la perte, et d'autant plus qu'ils sont larges** —
balayage monotone au-delà de 10 %, signe INVERSE de celui des États-Unis, où les sept
candidats étaient positifs. Un mécanisme réel ne change pas de signe d'un continent à
l'autre. Seul 10 % ressort positif, à t=0,20, c'est-à-dire rien.

**Témoin doublement contrôlé.** Contre `queues.portefeuille` sur les mêmes entrées :
écart max **0,00e+00** sur les trois séries (brut, échange, TTF), même motif de NaN —
le script refuse de continuer sinon. Et contre le CSV figé du 2026-10-10 :
−21,9 %/an, t −1,40, **1 128 jours**, rotation 26,3 %, TTF 0,96 % — les cinq valeurs
retrouvées. Le verdict EU est donc bien reproductible.

**Ce qui borne la portée de cette contre-épreuve** — à répéter avec le résultat :
- `reversal_21j` étant mort en EU, on mesure « le stop réduit-il une perte », pas
  « améliore-t-il la stratégie » ;
- le livre EU valide ne commence qu'en **2021** : 2020 est absent, et c'est l'année
  qui portait +42,7 points du gain américain. L'événement principal n'est pas testé ;
- la TTF des rachats de couverture déclenchés **en cours de tranche** n'est pas comptée
  (cohérence avec `couts.py`, qui ne taxe que les ouvertures), ce qui **flatte** le
  stop : −1,4 est une borne haute.

### ⚠️ `n_lignes` n'est pas `2n` — piège de lecture, une heure perdue

La colonne `n_lignes` de `data/eu/queues.csv` **n'est pas le nombre de lignes par
jambe**. `mesurer()` y écrit bien `2*n`, mais `main()` l'ÉCRASE à la ligne 517 par la
taille réelle du livre, `2*n*h//pas`. La ligne du verdict porte donc `n_lignes = 30`
pour **n = 5** (2×5×15/5 = 30), pas pour n=15.

Lu comme `2n`, ça donne n=15 — et la contre-épreuve du stop a d'abord été tournée
entièrement sur un livre de 90 lignes au lieu de 30, avec pour conséquence un témoin
à −11,2 %/an au lieu de −21,9 % et la fausse conclusion que le verdict figé n'était
pas reproductible. Il l'est, exactement. Pour mémoire, les trois configurations :

| | brut %/an | t | jours | rotation | TTF |
|---|---|---|---|---|---|
| **n=5** (le verdict) | **−21,9 %** | **−1,40** | **1 128** | 26,3 % | 0,96 % |
| n=15 | −11,2 % | −1,02 | 1 132 | 25,1 % | 1,08 % |
| n=15 `--liquide-partout` | −7,9 % | −0,78 | 1 132 | 24,9 % | 1,14 % |

`RESULTATS.md` disait « queue extrême n=5 » depuis le début. **La prose était juste,
c'est la lecture du CSV qui était fausse.** Deux correctifs en sont sortis, tous deux
utiles indépendamment de l'erreur :

1. ⚠️ **`queues.py` écrivait `data/eu/queues.csv` sans condition** : chaque `main()`
   REMPLAÇAIT le fichier par les lignes de son propre run. `data/*` étant gitignoré,
   il n'y avait ni historique ni récupération — un run partiel aurait détruit le
   détail du verdict. La sortie est désormais **horodatée**, et `queues.csv` reste le
   résultat figé du 10 octobre. Même motif et même correctif que la note
   `feedback_lots_compteur_ecrase` du projet US (une 2e passe y avait effacé 1 230
   symboles).
2. **Chaque ligne de sortie porte maintenant sa commande** (colonnes `genere` et
   `commande`). Une colonne et non un en-tête `#`, qui casserait un `read_csv` naïf.
   C'est le remède à ce qui s'est réellement passé : une heure passée à chercher des
   arguments qu'une colonne `commande` aurait donnés en deux secondes.

### Ne pas refaire sans élément neuf
Re-tester cette famille (reversal/momentum en queue extrême) en Europe n'a de sens que si :
un univers VRAIMENT plus large (STOXX 600 complet avec Italie + radiés, ou all-Europe),
OU une famille de signaux différente (pas reversal/trend), OU un edge à DEUX jambes.
Sinon, c'est déjà répondu. Détail chiffré figé : relancer `queues.py` sur le panel en cache.
