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

### Ne pas refaire sans élément neuf
Re-tester cette famille (reversal/momentum en queue extrême) en Europe n'a de sens que si :
un univers VRAIMENT plus large (STOXX 600 complet avec Italie + radiés, ou all-Europe),
OU une famille de signaux différente (pas reversal/trend), OU un edge à DEUX jambes.
Sinon, c'est déjà répondu. Détail chiffré figé : relancer `queues.py` sur le panel en cache.
