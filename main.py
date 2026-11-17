"""Forecast GTA VI's launch-day Twitch viewers hour by hour.

Competition: gta6-twitch-ccu-forecast-01 (make.fun, program/v1).

The program reads one case file per run (``/input/<id>.in``) and writes one
forecast (``/output/<id>.out``): for each of hours 2 to 24 of the release day
(UTC), five quantiles (5%, 25%, 50%, 75%, 95%) of that hour's concurrent
Twitch viewers in the game's category.

Model: a tiered lognormal ratio forecaster, calibrated at run time on the
case's own comparables (past big game launches' hourly Twitch curves).

  - Every comparable with a usable release day gives, for each hour h, a
    log-ratio ln(viewers_h / viewers_1): how that launch's viewership moved
    relative to its own first hour.  The first hour anchors the level; the
    ratios carry the shape of a launch day.
  - Launches are not one regime.  A game that had almost nobody watching in
    hour 1 (it unlocked later in the UTC day) explodes by 10x-1000x when its
    regions wake up; a game already live at UTC midnight with tens of
    thousands of viewers dips in the small hours and rises into the US
    evening, peaking around hours 18-21.  So the calibration set is tiered
    on the case's own hour-1 print: hour-1 >= 50,000 uses only comparables
    with hour-1 >= 50,000; >= 20,000 uses that tier; below that, all
    comparables.  A tier with fewer than 5 launches falls back to the next
    wider one.  (Chosen by leave-one-out pinball-loss scoring on the kit's
    comparables: the 50k tier scores ~0.21 against the house baseline's
    ~0.25 on the same launches; the unfiltered set scores ~0.71.)
  - For each hour, the quantiles are q_tau = p1 * exp(m + z_tau * sd), where
    p1 is hour 1's print, m and sd are the mean and sample standard
    deviation of that hour's log-ratios across the tier, and z_tau is the
    standard normal quantile at each level.  The spread is honest: it is the
    spread past launches actually showed, widening through the day as the
    launches diverge, instead of a fixed guess.

The program is deterministic (sorted inputs, no randomness, no clock, no
network) and standard-library only, so two runs on one case write the same
bytes.  It reads every ``*.in`` file in the input directory and writes one
``.out`` per case, so the grader's one-case run and a local run over the
kit's practice cases both work.  ``MAKEFUN_INPUT_DIR`` and
``MAKEFUN_OUTPUT_DIR`` stand in for ``/input`` and ``/output`` outside the
grader's container.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file would import.  (This entry is one file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level.
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Hour-1 print thresholds for the calibration tiers, high to low.  The tier
# used is the highest whose threshold the case's hour-1 print reaches and
# which still holds enough launches; below that, the next tier down.
TIERS = [50000, 20000, 0]
# A tier with fewer launches than this is too thin to calibrate on.
MIN_CALIB = 5
# Spread to use when an hour has a single calibration point.
DEFAULT_SD = 0.30
# The house baseline's spread, used only when an hour has no calibration
# point at all (a hole in every comparable's day).
BASELINE_SIGMA = 0.15


def parse_ts(text):
    """An ISO 8601 UTC timestamp as an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def round2(value):
    """Round to 2 decimals, half up, as JavaScript's Math.round does it.

    A whole number comes back as an int, so json.dumps writes 1240 where
    JavaScript writes 1240 (not 1240.0).
    """
    scaled = value * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    rounded = whole / 100
    return int(rounded) if float(rounded).is_integer() else rounded


def release_day_hours(comp):
    """A comparable's release-day hourly viewers, hour 1 to 24.

    ``hourly`` holds one point per sampled hour from 14 days before the
    release day to 3 days after it; ``day_start`` is 00:00 UTC of the
    release date.  A point's hour is its offset from day_start plus one.
    Points with no viewers, or a non-positive count, are skipped: the log
    of 0 is no number, and a missing hour simply does not calibrate it.
    """
    start = parse_ts(comp["day_start"])
    hours = {}
    for point in comp.get("hourly") or []:
        viewers = point.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        offset = (parse_ts(point["from"]) - start).total_seconds() / 3600
        hour = int(offset) + 1
        if 1 <= hour <= 24:
            hours[hour] = viewers
    return hours


def calibration_tier(comparables, p1):
    """The comparables to calibrate on, tiered on this case's hour-1 print.

    Returns a list of release-day hour dicts (each with a valid hour 1).
    The GTA VI pre-release comparable has no release day and drops out
    here, as does any comparable missing hour 1.
    """
    days = []
    for comp in comparables:
        hours = release_day_hours(comp)
        if 1 in hours and hours[1] > 0:
            days.append(hours)
    for threshold in TIERS:
        if p1 < threshold:
            continue
        tier = [d for d in days if d[1] >= threshold]
        if len(tier) >= MIN_CALIB:
            return tier
    return days


def hour_log_ratios(days, hour):
    """ln(viewers_h / viewers_1) across the calibration launches that have it."""
    ratios = []
    for hours in days:
        if hour in hours and hours[hour] > 0:
            ratios.append(math.log(hours[hour] / hours[1]))
    return ratios


def hour_quantiles(p1, days, hour):
    """The five quantiles for one hour, from that hour's log-ratio spread."""
    values = hour_log_ratios(days, hour)
    if len(values) >= 2:
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        sd = math.sqrt(var)
    elif len(values) == 1:
        mean, sd = values[0], DEFAULT_SD
    else:
        # No comparable has this hour: fall back to the house baseline's
        # flat median and widening spread rather than guessing a shape.
        mean, sd = 0.0, BASELINE_SIGMA * math.sqrt(hour - 1)
    quantiles = []
    previous = 0.0
    for z in Z:
        q = p1 * math.exp(mean + z * sd)
        q = round2(q)
        q = min(max(q, 0.01), 1_000_000_000)
        # Rounding can only tie, never fall, but keep the row ordered.
        q = max(q, previous)
        quantiles.append(q)
        previous = q
    return quantiles


def forecast_case(case, name):
    """One case's forecast: 23 rows, hours 2 to 24, five quantiles each."""
    known = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    p1 = 1.0
    if known is not None and known.get("viewers"):
        p1 = max(1.0, float(known["viewers"]))
    days = calibration_tier(case.get("comparables") or [], p1)
    rows = []
    for row in case.get("forecast") or []:
        hour = row["hour"]
        rows.append({"hour": hour, "q": hour_quantiles(p1, days, hour)})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
