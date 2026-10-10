# Actions EU — backtest

Portage européen de la stratégie de retournement en queue extrême du robot actions US
(`reversal_21j`, tranches chevauchantes, long/short). **Backtest-only** : produire le
coût mortel (TTF française incluse) et le `t` de Newey-West sur un univers EU large
(STOXX 600 / grandes-moyennes capis), avant d'envisager le moindre robot live.

> Dépôt **privé**. Séparé du projet actions US (`~/trading`) et du bot or. Voir `CLAUDE.md`.

## Démarrage
```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env            # renseigner EODHD_TOKEN (plan EU + radiés)
cd backtest/eu

# 1) GATE : EODHD sert-il les radiés EU ? (rien n'est fiable avant ce oui)
../../venv/bin/python eodhd.py              # témoins vivants + radiés
../../venv/bin/python eodhd.py --places     # confirmer les codes de place

# 2) Annuaire (listés + radiés) puis collecte EOD en lots (reprenable)
../../venv/bin/python univers.py
../../venv/bin/python eodhd.py --charger

# 3) Le chiffre de décision
../../venv/bin/python signaux.py            # sanity : t par signal/horizon
../../venv/bin/python queues.py --valider reversal_21j --n 5 --h 15 --pas 5
```

## Ce qui est réutilisé vs neuf
- **Réutilisé du projet US** (le vrai IP, ~inchangé) : `signaux.py` (signaux, `t` Newey-West),
  `queues.py` (le juge : tranches chevauchantes, rotation exacte, coût mortel, bootstrap).
- **Neuf, spécifique EU** : `eodhd.py` (données + gate radiés), `univers.py` (annuaire EU),
  `couts.py` (TTF française dans le coût mortel).

## Lecture du résultat
`queues.py` sort, par configuration : rendement net de TTF, `TTF/an`, `t`, nets à 2/10 pb,
et le **coût mortel** (pb/jambe qui annule le gain, TTF déjà payée). Seuil de conviction du
projet : **|t| > 3**. Caveats devise/composition/TTF : voir `CLAUDE.md`.
