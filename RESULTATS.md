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
fallait un autre échantillon pour le dire. Mesuré ici par **`backtest/eu/sortie_stop.py`**,
n=15 h=15 pas=5 delai=1, net 5 pb/jambe, TTF payée.

| stop | 10 % | 15 % | 20 % | 25 % | 30 % | 40 % |
|---|---|---|---|---|---|---|
| écart vs témoin (pt/an) | −0,7 | −1,2 | −1,4 | −2,2 | −2,9 | −2,9 |
| t de l'écart | −0,20 | −0,45 | −0,67 | −1,24 | −1,78 | −1,92 |

**Les six aggravent la perte, et d'autant plus que le stop est large** — balayage
monotone, signe INVERSE de celui des États-Unis. Un mécanisme réel ne change pas de
signe d'un continent à l'autre. Insensible à l'univers : −1,4 par défaut, −1,5 en
`--liquide-partout`.

Témoin contrôlé contre `queues.portefeuille` : écart max **0,00e+00** sur les trois
séries (brut, échange, TTF), même motif de NaN. Le script refuse de continuer sinon.

**Ce qui borne la portée de cette contre-épreuve** — à répéter avec le résultat :
- `reversal_21j` étant mort en EU, on mesure « le stop réduit-il une perte », pas
  « améliore-t-il la stratégie » ;
- le livre EU valide ne commence qu'en **2021** : 2020 est absent, et c'est l'année
  qui portait +42,7 points du gain américain. L'événement principal n'est pas testé ;
- la TTF des rachats de couverture déclenchés **en cours de tranche** n'est pas comptée
  (cohérence avec `couts.py`, qui ne taxe que les ouvertures), ce qui **flatte** le
  stop : −1,4 est une borne haute.

### ⚠️ Le chiffre figé du 10 octobre n'est pas reproductible en l'état

En construisant le témoin, impossible de retrouver la ligne `reversal_21j` du CSV
(−21,9 %/an, t −1,40, 1 128 jours, rotation 26,3 %, TTF 0,96 %) :

| | brut %/an | t | jours | rotation | TTF |
|---|---|---|---|---|---|
| CSV du 2026-10-10 | −21,9 % | −1,40 | 1 128 | 26,3 % | 0,96 % |
| univers par défaut | −11,2 % | −1,02 | 1 132 | 25,1 % | 1,08 % |
| `--liquide-partout` | −7,9 % | −0,78 | 1 132 | 24,9 % | 1,14 % |

Le drapeau **éloigne** du chiffre figé, et l'écart porte aussi sur la rotation et
l'assiette TTF : c'est donc l'UNIVERS qui diffère, pas une convention de calcul.
**Les arguments de ligne de commande qui ont produit ce CSV ne sont écrits nulle
part** — « relancer `queues.py` sur le panel en cache » ne suffit pas à le refaire.
Le verdict NO-GO n'est pas remis en cause (il tient sur 3 signaux × 2 univers, et
`reversal_21j` est négatif dans les trois mesures ci-dessus), mais son détail chiffré
n'est pas vérifiable tant que ces arguments ne sont pas retrouvés.

⚠️ **`queues.py:545` écrit `data/eu/queues.csv` sans condition** : chaque `main()`
REMPLACE le fichier par les lignes de son propre run. `data/*` étant gitignoré, il
n'y a ni historique ni récupération — un run partiel détruirait le détail du verdict.
Même motif que la note `feedback_lots_compteur_ecrase` du projet US (une 2e passe
avait effacé 1 230 symboles) et même correctif : **horodater le nom de sortie**.

### Ne pas refaire sans élément neuf
Re-tester cette famille (reversal/momentum en queue extrême) en Europe n'a de sens que si :
un univers VRAIMENT plus large (STOXX 600 complet avec Italie + radiés, ou all-Europe),
OU une famille de signaux différente (pas reversal/trend), OU un edge à DEUX jambes.
Sinon, c'est déjà répondu. Détail chiffré figé : relancer `queues.py` sur le panel en cache.
