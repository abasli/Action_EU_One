# Actions EU — instructions projet

Portage de la stratégie de retournement en **queue extrême** (`reversal_21j`,
tranches chevauchantes) du robot actions US vers les **actions européennes**.
Univers cible : **STOXX 600 / grandes et moyennes capis EU liquides**.

> **Statut : backtest-only.** On ne construit AUCUN robot live (pas de broker, pas
> de `bot/`) tant que le backtest n'a pas passé la barre. Dépôt séparé `Action_EU_One`,
> créé le 2026-10-10. Projet frère : robot actions US (`~/trading`, `Actions_US_One`).

## La question à trancher, et dans cet ordre
1. **Gate biais de survivance** : EODHD sert-il les radiés EU ? (`eodhd.py` sans argument).
   Rien n'est fiable avant ce « oui ». C'est la discipline héritée des US.
2. **Coût mortel, TTF incluse** + `|t|` de Newey-West sur `reversal_21j`. C'est LE chiffre
   de décision. Si le coût mortel ne dépasse pas une exécution réaliste, on s'arrête là.

## Méthodologie reportée des US (ne pas renégocier sans mesure)
- **Coût mortel** = coût par jambe qui annule le gain. Métrique de décision du projet.
  Ici il se lit **TTF française déjà payée** (0,30 % sur les achats de large-caps FR,
  modélisée dans `couts.py` — jamais supposée).
- **Seuil de conviction : |t| > 3** (Newey-West, lag = horizon). En dessous, dire que ce
  n'est pas concluant plutôt que de conclure.
- **Queue extrême, pas déciles** : le signal vit dans la queue d'un univers LARGE. Le `t`
  décroît quand on élargit la sélection — c'est pourquoi le CAC 40 seul ne marche pas.
- Coûter la **rotation réelle**, jamais les seuls événements.

## Caveats explicites (à répéter dans toute conclusion)
- **Multi-devises** : rendements en devise locale (classement relatif OK), mais la P&L EUR
  et le coût mortel EN EUROS exigent la conversion FX — raffinement non encore branché.
- **Composition** : univers « EU liquides », pas appartenance STOXX 600 point-in-time
  (pas de source gratuite) — borne le biais de sélection par la liquidité, à documenter.
- **TTF** : assiette = acquisitions à l'ouverture des tranches ; rééquilibrage non taxé
  (premier jet) ; seuil 1 Md€ sur capi courante ; émetteur FR approché par ISIN « FR ».

## Environnement
- Python : `venv/bin/python` depuis la racine. Modules dans `backtest/eu/`.
- Données (EODHD) : `.env` → `EODHD_TOKEN` (jamais committé).
- Lancer depuis `backtest/eu/` (imports locaux `import eodhd`, `import signaux`, …).

## Sécurité — jamais committé
`.env` (clé EODHD), `data/*`, `logs/`. Le dépôt doit rester **privé**.
Grep chaque diff avant commit (préfixes de jetons, clés, chaînes longues).

## Ne pas citer une référence sans l'avoir vérifiée
Vérifier la doc / tester plutôt que supposer (endpoints EODHD, codes de place,
dates de radiation des témoins — tous confirmés empiriquement au gate).
