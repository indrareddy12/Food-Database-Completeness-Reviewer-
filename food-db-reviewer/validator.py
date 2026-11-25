"""Stage 1 Deterministic Food Database Completeness Validator.

Validates raw food product records against Tier 1 (Safety-Critical),
Tier 2 (Regulatory/Nutrition), and Tier 3 (Catalog Metadata) rules without
ever inventing, estimating, or modifying missing or invalid values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

PriorityLevel = Literal["HIGH", "MEDIUM", "LOW", "NONE"]
TierName = Literal["TIER_1_SAFETY", "TIER_2_NUTRITION", "TIER_3_METADATA"]


@dataclass(frozen=True)
class FieldRule:
    """Schema rule describing a required product field and its risk tier."""

    name: str
    tier: TierName
    kind: Literal["list_or_text", "number", "text"]


FIELD_RULES: tuple[FieldRule, ...] = (
    # Tier 1: Safety-Critical
    FieldRule("ingredients", "TIER_1_SAFETY", "list_or_text"),
    FieldRule("allergens", "TIER_1_SAFETY", "list_or_text"),
    # Tier 2: Regulatory / Nutrition
    FieldRule("calories", "TIER_2_NUTRITION", "number"),
    FieldRule("protein_g", "TIER_2_NUTRITION", "number"),
    FieldRule("carbs_g", "TIER_2_NUTRITION", "number"),
    FieldRule("fat_g", "TIER_2_NUTRITION", "number"),
    FieldRule("sugar_g", "TIER_2_NUTRITION", "number"),
    FieldRule("sodium_mg", "TIER_2_NUTRITION", "number"),
    # Tier 3: Catalog Metadata
    FieldRule("brand", "TIER_3_METADATA", "text"),
    FieldRule("category", "TIER_3_METADATA", "text"),
    FieldRule("serving_size", "TIER_3_METADATA", "text"),
)

# Common dirty-data placeholder strings that represent missing data, not valid values.
PLACEHOLDER_STRINGS: frozenset[str] = frozenset(
    {"", "n/a", "na", "tbd", "unknown", "null", "none", "missing", "-", "?"}
)


class InvalidFieldDetail(BaseModel):
    """Describes an invalid (corrupted or malformed) field without altering its raw value."""

    field: str
    tier: TierName
    raw_value: Any
    reason: str


class MissingFieldDetail(BaseModel):
    """Describes a missing or placeholder field."""

    field: str
    tier: TierName
    raw_value: Any
    reason: str


class RecordAuditResult(BaseModel):
    """Stage 1 deterministic audit report for a single food product record."""

    id: str
    name: str
    missing_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    missing_details: list[MissingFieldDetail] = Field(default_factory=list)
    invalid_details: list[InvalidFieldDetail] = Field(default_factory=list)
    baseline_priority: PriorityLevel
    needs_llm_review: bool


class AuditSummary(BaseModel):
    """Aggregate summary across all audited database records."""

    total_records: int
    records_needing_llm_review: int
    records_short_circuited: int
    priority_counts: dict[PriorityLevel, int]


class DatabaseAuditReport(BaseModel):
    """Complete Stage 1 deterministic audit output."""

    pipeline_stage: str = "STAGE_1_DETERMINISTIC_VALIDATOR"
    zero_hallucination_mode: bool = True
    summary: AuditSummary
    results: list[RecordAuditResult]


def _is_placeholder_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in PLACEHOLDER_STRINGS


def _classify_field(
    record: dict[str, Any], rule: FieldRule
) -> tuple[MissingFieldDetail | None, InvalidFieldDetail | None]:
    """Check one field against its rule; returns (missing_detail, invalid_detail)."""
    if rule.name not in record or record[rule.name] is None:
        return (
            MissingFieldDetail(
                field=rule.name,
                tier=rule.tier,
                raw_value=record.get(rule.name),
                reason="Value is null or absent.",
            ),
            None,
        )

    raw_val = record[rule.name]

    if rule.kind == "text":
        if _is_placeholder_str(raw_val):
            return (
                MissingFieldDetail(
                    field=rule.name,
                    tier=rule.tier,
                    raw_value=raw_val,
                    reason="Text field is empty or a placeholder string.",
                ),
                None,
            )
        if not isinstance(raw_val, str):
            return (
                None,
                InvalidFieldDetail(
                    field=rule.name,
                    tier=rule.tier,
                    raw_value=raw_val,
                    reason=f"Expected string, got {type(raw_val).__name__}.",
                ),
            )
        return None, None

    if rule.kind == "list_or_text":
        if isinstance(raw_val, list):
            cleaned = [item for item in raw_val if isinstance(item, str) and item.strip()]
            if len(raw_val) == 0:
                return (
                    MissingFieldDetail(
                        field=rule.name,
                        tier=rule.tier,
                        raw_value=raw_val,
                        reason="List is empty; declaration is missing.",
                    ),
                    None,
                )
            if len(cleaned) != len(raw_val):
                return (
                    None,
                    InvalidFieldDetail(
                        field=rule.name,
                        tier=rule.tier,
                        raw_value=raw_val,
                        reason="List contains non-string or blank entries.",
                    ),
                )
            return None, None

        if _is_placeholder_str(raw_val):
            return (
                MissingFieldDetail(
                    field=rule.name,
                    tier=rule.tier,
                    raw_value=raw_val,
                    reason="Declaration is empty or a placeholder string.",
                ),
                None,
            )

        if not isinstance(raw_val, str):
            return (
                None,
                InvalidFieldDetail(
                    field=rule.name,
                    tier=rule.tier,
                    raw_value=raw_val,
                    reason=f"Expected list or string, got {type(raw_val).__name__}.",
                ),
            )
        return None, None

    # rule.kind == "number"
    if _is_placeholder_str(raw_val):
        # "unknown" in numeric field is explicitly flagged as an invalid/non-numeric value;
        # standard placeholders like "N/A" and "TBD" are flagged as missing.
        if isinstance(raw_val, str) and raw_val.strip().lower() == "unknown":
            return (
                None,
                InvalidFieldDetail(
                    field=rule.name,
                    tier=rule.tier,
                    raw_value=raw_val,
                    reason="Non-numeric string ('unknown') in numeric nutrition field.",
                ),
            )
        return (
            MissingFieldDetail(
                field=rule.name,
                tier=rule.tier,
                raw_value=raw_val,
                reason=f"Placeholder string ({raw_val!r}) instead of numeric value.",
            ),
            None,
        )

    if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
        return (
            None,
            InvalidFieldDetail(
                field=rule.name,
                tier=rule.tier,
                raw_value=raw_val,
                reason=f"Expected non-negative number, got {raw_val!r}.",
            ),
        )

    if raw_val < 0:
        return (
            None,
            InvalidFieldDetail(
                field=rule.name,
                tier=rule.tier,
                raw_value=raw_val,
                reason=f"Physically impossible negative nutrition value ({raw_val}).",
            ),
        )

    return None, None


def _compute_baseline_priority(
    missing_details: list[MissingFieldDetail],
    invalid_details: list[InvalidFieldDetail],
) -> PriorityLevel:
    """Compute deterministic review priority from field tiers and error severity."""
    all_issues = [*missing_details, *invalid_details]
    if not all_issues:
        return "NONE"

    # Tier 1 safety-critical gaps or corrupted/invalid Tier 2 nutrition values -> HIGH
    has_tier1_issue = any(item.tier == "TIER_1_SAFETY" for item in all_issues)
    has_tier2_invalid = any(item.tier == "TIER_2_NUTRITION" for item in invalid_details)
    if has_tier1_issue or has_tier2_invalid:
        return "HIGH"

    # Missing Tier 2 nutrition fields -> MEDIUM
    if any(item.tier == "TIER_2_NUTRITION" for item in missing_details):
        return "MEDIUM"

    # Tier 3 catalog metadata gaps only -> LOW
    return "LOW"


def audit_record(record: dict[str, Any]) -> RecordAuditResult:
    """Run deterministic completeness and validity checks on one product record."""
    missing_details: list[MissingFieldDetail] = []
    invalid_details: list[InvalidFieldDetail] = []

    for rule in FIELD_RULES:
        missing, invalid = _classify_field(record, rule)
        if missing is not None:
            missing_details.append(missing)
        if invalid is not None:
            invalid_details.append(invalid)

    priority = _compute_baseline_priority(missing_details, invalid_details)
    needs_llm_review = priority != "NONE"

    return RecordAuditResult(
        id=str(record.get("id", "UNKNOWN")),
        name=str(record.get("name", "Unnamed Product")),
        missing_fields=[d.field for d in missing_details],
        invalid_fields=[d.field for d in invalid_details],
        missing_details=missing_details,
        invalid_details=invalid_details,
        baseline_priority=priority,
        needs_llm_review=needs_llm_review,
    )


def audit_database(records: list[dict[str, Any]]) -> DatabaseAuditReport:
    """Validate all records and assemble the full Stage 1 JSON audit report."""
    results = [audit_record(record) for record in records]
    priority_counts: dict[PriorityLevel, int] = {
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "NONE": 0,
    }
    for res in results:
        priority_counts[res.baseline_priority] += 1

    needing_review = sum(1 for res in results if res.needs_llm_review)
    summary = AuditSummary(
        total_records=len(results),
        records_needing_llm_review=needing_review,
        records_short_circuited=len(results) - needing_review,
        priority_counts=priority_counts,
    )
    return DatabaseAuditReport(summary=summary, results=results)


def main() -> None:
    """Load sample_data.json, run Stage 1 validation, and print JSON report."""
    data_path = Path(__file__).resolve().parent / "sample_data.json"
    with data_path.open("r", encoding="utf-8") as f:
        records: list[dict[str, Any]] = json.load(f)

    report = audit_database(records)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
