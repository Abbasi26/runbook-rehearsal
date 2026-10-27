"""Weighted maturity score.

Skip findings are excluded. A dimension with no scored findings drops out and
its weight is shared across the dimensions that did produce scored findings.
Each runbook score is rounded to one decimal. The overall score is the
equal-weight mean of those rounded runbook scores, rounded the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from rehearse.models import Finding

WEIGHTS: dict[str, int] = {
    "freshness": 20,
    "contacts": 15,
    "reachability": 25,
    "references": 20,
    "directory": 10,
    "completeness": 10,
}

STATUS_VALUE = {
    "pass": 1.0,
    "warn": 0.5,
    "fail": 0.0,
}

BANDS = (
    (90.0, "maintained", "Maintained"),
    (75.0, "usable", "Usable with gaps"),
    (50.0, "drifting", "Drifting"),
    (25.0, "stale", "Stale"),
    (0.0, "not-rehearsable", "Not rehearsable"),
)


def round1(value: float) -> float:
    quantized = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(quantized)


def band_for(score: float) -> tuple[str, str]:
    for threshold, name, label in BANDS:
        if score >= threshold:
            return name, label
    return "not-rehearsable", "Not rehearsable"


@dataclass
class DimensionScore:
    dimension: str
    weight: int
    effective_weight: float
    ratio: float
    contribution: float
    counts: dict[str, int]


@dataclass
class Score:
    value: float | None
    band: str
    band_label: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def _counts(findings: list[Finding]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for finding in findings:
        if finding.status in counts:
            counts[finding.status] += 1
    return counts


def score_findings(findings: list[Finding]) -> Score:
    counts = _counts(findings)
    grouped: dict[str, list[Finding]] = {name: [] for name in WEIGHTS}
    for finding in findings:
        if finding.status == "skip" or finding.status not in STATUS_VALUE:
            continue
        if finding.dimension not in grouped:
            continue
        grouped[finding.dimension].append(finding)

    active = {name: items for name, items in grouped.items() if items}
    if not active:
        return Score(None, "not-rehearsable", "Not rehearsable", [], counts)

    weight_sum = sum(WEIGHTS[name] for name in active)
    total = 0.0
    details: list[DimensionScore] = []
    for name in WEIGHTS:
        items = active.get(name)
        if not items:
            continue
        ratio = sum(STATUS_VALUE[item.status] for item in items) / len(items)
        effective = WEIGHTS[name] / weight_sum * 100
        contribution = ratio * effective
        total += contribution
        dim_counts = _counts(items)
        details.append(
            DimensionScore(
                dimension=name,
                weight=WEIGHTS[name],
                effective_weight=round1(effective),
                ratio=round1(ratio),
                contribution=round1(contribution),
                counts=dim_counts,
            )
        )
    value = round1(total)
    band, label = band_for(value)
    return Score(value, band, label, details, counts)


def overall_score(scores: list[float]) -> Score:
    if not scores:
        return Score(None, "not-rehearsable", "Not rehearsable")
    value = round1(sum(scores) / len(scores))
    band, label = band_for(value)
    return Score(value, band, label)
