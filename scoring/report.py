"""CalibrationReport dataclass.

Structured deliverable for Market 2 consumers (small calibration
consultancies, M&V practitioners). Built per miner per round from a
VerifiedResult plus round context; serializable to JSON for logging,
debugging, and future synapse payload use.

Pure data. No I/O, no DB access, no logging. Storage and synapse
plumbing arrive in a later change (Phase 2a part 2).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CalibrationReport:
    """Structured per-miner-per-round calibration report.

    Mirrors what a Market 2 practitioner would expect to hand a client
    as part of an ASHRAE Guideline 14 deliverable: identification,
    windows, calibrated parameters, fit quality (hourly and monthly),
    per-output breakdown, and compliance flags against the four
    Guideline 14 bands.

    Rejected submissions (where verification_reason is set) populate
    identification and parameter fields but carry NaN metrics and
    False compliance flags; readers can see WHY a calibration failed.
    """

    # Identification
    round_id: str
    miner_uid: int
    miner_hotkey: str
    test_case_id: str
    manifest_version: str
    spec_version: int

    # Windows (hours, relative to test case simulation year start)
    training_period_start_hour: int
    training_period_end_hour: int
    test_period_start_hour: int
    test_period_end_hour: int

    # Calibrated parameters as submitted (may be empty for rejected submissions)
    calibrated_parameters: dict[str, float] = field(default_factory=dict)

    # Aggregate fit quality
    hourly_cvrmse: float = float("nan")
    hourly_nmbe: float = float("nan")
    hourly_r_squared: float = float("nan")
    monthly_cvrmse: float = float("nan")
    monthly_nmbe: float = float("nan")

    # Per-output breakdown. Outer key is scoring output name (e.g. zone_air_temperature_C);
    # inner dict carries hourly_cvrmse / hourly_nmbe / hourly_r_squared for that output.
    per_output_metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    # ASHRAE Guideline 14 compliance flags
    ashrae_hourly_cvrmse_pass: bool = False
    ashrae_hourly_nmbe_pass: bool = False
    ashrae_monthly_cvrmse_pass: bool = False
    ashrae_monthly_nmbe_pass: bool = False
    ashrae_overall_pass: bool = False

    # Round-level metadata
    simulations_used: int = 0
    verification_reason: str | None = None

    # Timestamp (ISO 8601 UTC, populated by the builder)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict view of the report.

        Non-finite metric values are coerced to None so the result
        survives a round-trip through json.dumps / json.loads without
        becoming a JSON parse error. from_dict restores them to NaN.
        """
        data = asdict(self)
        for key in (
            "hourly_cvrmse",
            "hourly_nmbe",
            "hourly_r_squared",
            "monthly_cvrmse",
            "monthly_nmbe",
        ):
            value = data[key]
            if isinstance(value, float) and not math.isfinite(value):
                data[key] = None
        for out_key, out_metrics in list(data["per_output_metrics"].items()):
            cleaned: dict[str, float | None] = {}
            for metric_key, metric_value in out_metrics.items():
                if isinstance(metric_value, float) and not math.isfinite(metric_value):
                    cleaned[metric_key] = None
                else:
                    cleaned[metric_key] = metric_value
            data["per_output_metrics"][out_key] = cleaned
        return data

    def to_json(self, indent: int | None = None) -> str:
        """Serialize to a JSON string. Pass indent for human-readable output."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationReport:
        """Reconstruct a CalibrationReport from its dict representation.

        None values for metric fields are restored to NaN so downstream
        code can rely on metrics being finite-or-NaN floats.
        """
        restored = dict(data)
        for key in (
            "hourly_cvrmse",
            "hourly_nmbe",
            "hourly_r_squared",
            "monthly_cvrmse",
            "monthly_nmbe",
        ):
            if restored.get(key) is None:
                restored[key] = float("nan")
        per_output_in = restored.get("per_output_metrics", {}) or {}
        per_output_out: dict[str, dict[str, float]] = {}
        for out_key, out_metrics in per_output_in.items():
            per_output_out[out_key] = {
                metric_key: (float("nan") if metric_value is None else float(metric_value))
                for metric_key, metric_value in out_metrics.items()
            }
        restored["per_output_metrics"] = per_output_out
        restored.setdefault("calibrated_parameters", {})
        return cls(**restored)
