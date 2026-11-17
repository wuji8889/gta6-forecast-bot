# GTA VI launch-day Twitch forecaster

Entry for make.fun's `gta6-twitch-ccu-forecast-01`: forecast the concurrent
Twitch viewers in the "Grand Theft Auto VI" category for each of hours 2 to
24 of release day (2026-11-19 UTC), as five quantiles (5%, 25%, 50%, 75%,
95%) per hour. Scored by mean pinball loss on the log scale; a prize needs
a loss strictly below the best house entry (baseline or house model).

## Model

A tiered lognormal ratio forecaster, calibrated at run time on the case's
own comparables (past big game launches' hourly Twitch curves, SullyGnome):

- Hour 1's print anchors the level. Every comparable contributes, per hour
  h, a log-ratio `ln(viewers_h / viewers_1)` — the shape of a launch day,
  scale-free.
- Launches are not one regime. A game with almost nobody watching in hour
  1 (it unlocked later in the UTC day) explodes 10x–1000x when its regions
  wake up; a game already live at UTC midnight with tens of thousands of
  viewers dips in the small hours and rises into the US evening, peaking
  around hours 18–21. So the calibration set is tiered on the case's own
  hour-1 print: `>= 50,000` uses only comparables with hour-1 `>= 50,000`;
  `>= 20,000` uses that tier; below that, all comparables. A tier with
  fewer than 5 launches falls back to the next wider one.
- Per hour, the quantiles are `q_tau = p1 * exp(m + z_tau * sd)`, with `m`
  and `sd` the mean and sample standard deviation of that hour's
  log-ratios, and `z_tau` the standard normal quantile at each level. The
  spread is the spread past launches actually showed — it widens through
  the day as launches diverge — instead of a fixed guess.

## Local check

Leave-one-out pinball loss on the kit's comparables (37 launches with a
usable hour 1), scoring each launch against the others:

| model | launches | mean pinball loss |
|---|---|---|
| house baseline (flat, 0.15 spread) | hour-1 >= 50k (n=20) | 0.2509 |
| this forecaster | hour-1 >= 50k (n=20) | **0.2119** |
| this forecaster | all 37 | 0.5949 |

The all-37 figure is dragged down by the tiny-hour-1 regime (games not
yet unlocked at UTC midnight), where any hour-1-anchored forecast
struggles; GTA VI unlocks at midnight local with New Zealand, Europe and
the UK already live in hour 1, so the `>= 50k` tier is the relevant one.
Pre-launch category level carries no signal for the day's shape
(correlation ~0 with the evening peak ratio), so it is not used.

## Run

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network, deterministic: two runs
on one case write the same bytes (about 0.05 s a case). Reads every
`*.in` file in the input directory and writes one `.out` per case.

## Files

- `main.py` — the forecaster (the entrypoint the grader runs).
- `LICENSE` — MIT.
