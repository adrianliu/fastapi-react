"""Comparison statistics for an eval run (spec 6.5)."""

import random
from statistics import fmean, median

from .models import Bootstrap, EvalTask, ItemRate, RubricItem, Trial, VariantStats, Verdict

MARGIN = 0.05
RESAMPLES = 5000
MIN_PAIRED_TASKS = 3
HIST_BINS = 40


def _done(trials: list[Trial]) -> list[Trial]:
    return [t for t in trials if t.score is not None]


def variant_stats(variant: str, trials: list[Trial], tasks: list[EvalTask]) -> VariantStats:
    mine = _done([t for t in trials if t.variant == variant])
    non_control = {t.name for t in tasks if not t.control}
    item_trials = [t for t in mine if t.task in non_control]
    applied = [t.fix_applied for t in mine if t.fix_applied is not None]

    def mean_of(values: list[int | float | None]) -> float:
        present = [float(v) for v in values if v is not None]
        return fmean(present) if present else 0.0

    return VariantStats(
        variant=variant,
        trials=len(mine),
        check_pass=sum(1 for t in mine if t.check_pass),
        rubric_mean=round(mean_of([t.score for t in mine]), 3),
        median_diff_lines=median([t.diff_lines for t in mine if t.diff_lines is not None] or [0]),
        new_config=sum(1 for t in item_trials if t.items.get("added_new_config")),
        item_trials=len(item_trials),
        mean_tool_errors=round(mean_of([t.tool_errors for t in mine]), 2),
        mean_tokens=round(mean_of([t.tokens for t in mine])),
        mean_duration_s=round(mean_of([t.duration_s for t in mine])),
        mean_cost_usd=round(mean_of([t.cost_usd for t in mine]), 3),
        fix_applied=sum(applied) if applied else None,
    )


def item_rates(
    rubric: list[RubricItem], trials: list[Trial], tasks: list[EvalTask], variants: list[str]
) -> list[ItemRate]:
    """Per-item rates over the non-control tasks: 'added a feature flag 7/9 -> 1/9'."""
    non_control = {t.name for t in tasks if not t.control}
    base, cand = variants[0], variants[-1]
    rows = []
    for item in rubric:

        def hits(variant: str, key: str = item.key) -> list[bool]:
            return [
                t.items.get(key, False)
                for t in _done(trials)
                if t.variant == variant and t.task in non_control
            ]

        b, c = hits(base), hits(cand)
        rows.append(
            ItemRate(
                key=item.key,
                label=item.label,
                bad=item.bad,
                baseline=sum(b),
                candidate=sum(c),
                n=max(len(b), len(c)),
            )
        )
    return rows


def paired_bootstrap(
    trials: list[Trial], variants: list[str], *, seed: int = 0, resamples: int = RESAMPLES
) -> Bootstrap:
    """Paired comparison over tasks: per task, mean candidate score minus mean baseline score."""
    base, cand = variants[0], variants[-1]
    by_task: dict[str, dict[str, list[float]]] = {}
    for t in _done(trials):
        assert t.score is not None
        by_task.setdefault(t.task, {}).setdefault(t.variant, []).append(t.score)
    diffs = [
        fmean(v[cand]) - fmean(v[base]) for v in by_task.values() if v.get(base) and v.get(cand)
    ]
    hist_min, hist_max = -1.0, 1.0
    if len(diffs) < MIN_PAIRED_TASKS:
        return Bootstrap(
            verdict="too_few_tasks",
            delta=round(fmean(diffs), 3) if diffs else 0.0,
            ci_low=0.0,
            ci_high=0.0,
            margin=MARGIN,
            resamples=0,
            paired_tasks=len(diffs),
            histogram=[0] * HIST_BINS,
            hist_min=hist_min,
            hist_max=hist_max,
        )

    rng = random.Random(seed)
    means = sorted(fmean(rng.choices(diffs, k=len(diffs))) for _ in range(resamples))
    lo = means[int(0.025 * resamples)]
    hi = means[int(0.975 * resamples) - 1]
    verdict: Verdict = "no_clear_difference"
    if lo > MARGIN:
        verdict = "better"
    elif hi < -MARGIN:
        verdict = "worse"

    histogram = [0] * HIST_BINS
    width = (hist_max - hist_min) / HIST_BINS
    for m in means:
        histogram[min(HIST_BINS - 1, max(0, int((m - hist_min) / width)))] += 1
    return Bootstrap(
        verdict=verdict,
        delta=round(fmean(diffs), 3),
        ci_low=round(lo, 3),
        ci_high=round(hi, 3),
        margin=MARGIN,
        resamples=resamples,
        paired_tasks=len(diffs),
        histogram=histogram,
        hist_min=hist_min,
        hist_max=hist_max,
    )
