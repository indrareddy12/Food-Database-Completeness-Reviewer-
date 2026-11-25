"""Stage 1 Deterministic Auditor for OpenFoodFacts-style Food CSV Databases.

Audits CSV product records for missing fields, placeholder strings, duplicate
barcodes, physically impossible per-100g nutrition values, and consistency
errors without ever inventing, estimating, or modifying missing data.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

PriorityLevel = Literal["HIGH", "MEDIUM", "LOW", "NONE"]

PLACEHOLDER_STRINGS: frozenset[str] = frozenset(
    {"", "n/a", "na", "tbd", "unknown", "null", "none", "missing", "-", "?"}
)

TIER_1_SAFETY = ("ingredients_text", "allergens")
TIER_2_NUTRITION = (
    "energy_kcal_100g",
    "fat_100g",
    "saturated_fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "added_sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
)
TIER_3_METADATA = ("product_name", "brands", "categories", "serving_size")

GRAM_NUTRIENTS_100G = (
    "fat_100g",
    "saturated_fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "added_sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
)


class CsvAuditRecord(BaseModel):
    """Audit result for a single CSV food database row."""

    row_index: int
    code: str
    product_name: str | None
    brands: str | None
    missing_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    invalid_reasons: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    nutrition_completeness_pct: float | None = None
    baseline_priority: PriorityLevel
    needs_llm_review: bool


class CsvAuditSummary(BaseModel):
    """Database-wide quality and completeness metrics."""

    total_rows: int
    unique_codes: int
    duplicate_rows: int
    records_needing_llm_review: int
    records_short_circuited: int
    priority_counts: dict[PriorityLevel, int]
    missing_field_counts: dict[str, int]
    invalid_field_counts: dict[str, int]
    zero_nutrition_rows: int
    avg_nutrition_completeness_pct: float


class CsvDatabaseAuditReport(BaseModel):
    """Complete CSV database audit report."""

    source_file: str
    zero_hallucination_mode: bool = True
    summary: CsvAuditSummary
    results: list[CsvAuditRecord]


def is_missing_value(val: Any) -> bool:
    """Return True if value is NaN, None, or a dirty placeholder string."""
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str) and val.strip().lower() in PLACEHOLDER_STRINGS:
        return True
    return False


def parse_clean_float(val: Any) -> tuple[float | None, str | None]:
    """Parse numeric field without inventing data. Returns (number, error_reason)."""
    if is_missing_value(val):
        return None, None
    if isinstance(val, bool):
        return None, f"Boolean {val!r} is not a valid numeric value."
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None, "Non-finite numeric value."
        return float(val), None
    if isinstance(val, str):
        try:
            num = float(val.strip())
            if math.isnan(num) or math.isinf(num):
                return None, "Non-finite numeric value."
            return num, None
        except ValueError:
            return None, f"Non-numeric string {val!r}."
    return None, f"Unsupported type {type(val).__name__}."


def clean_str(val: Any) -> str | None:
    """Return stripped string if present and non-placeholder, else None."""
    if is_missing_value(val):
        return None
    return str(val).strip()


def audit_csv_row(row_index: int, row: dict[str, Any]) -> CsvAuditRecord:
    """Deterministically audit one CSV record against Tier 1/2/3 & sanity bounds."""
    code = clean_str(row.get("code")) or f"ROW-{row_index}"
    product_name = clean_str(row.get("product_name"))
    brands = clean_str(row.get("brands"))

    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    invalid_reasons: dict[str, str] = {}
    warnings: list[str] = []

    # Tier 1: Safety-critical text declarations
    for col in TIER_1_SAFETY:
        val = row.get(col)
        if is_missing_value(val):
            missing_fields.append(col)
        elif isinstance(val, str) and "\ufffd" in val:
            warnings.append(f"{col} contains encoding replacement character (U+FFFD).")

    # Tier 3: Catalog metadata
    for col in TIER_3_METADATA:
        val = row.get(col)
        if is_missing_value(val):
            missing_fields.append(col)
        elif col == "product_name" and str(val).strip() == code:
            invalid_fields.append("product_name")
            invalid_reasons["product_name"] = "Product name equals barcode instead of a real name."
        elif isinstance(val, str) and "\ufffd" in val:
            warnings.append(f"{col} contains encoding replacement character (U+FFFD).")

    # Tier 2: Nutrition fields per 100g
    parsed_nums: dict[str, float] = {}
    for col in TIER_2_NUTRITION:
        raw = row.get(col)
        if is_missing_value(raw):
            missing_fields.append(col)
            continue

        num, err = parse_clean_float(raw)
        if err is not None:
            invalid_fields.append(col)
            invalid_reasons[col] = err
            continue

        assert num is not None
        parsed_nums[col] = num

        if num < 0:
            invalid_fields.append(col)
            invalid_reasons[col] = f"Negative value ({num}) is physically impossible."
        elif col == "energy_kcal_100g" and num > 900:
            invalid_fields.append(col)
            invalid_reasons[col] = (
                f"Energy {num} kcal/100g exceeds max ~900 kcal/100g (likely kJ or per-pack error)."
            )
        elif col in GRAM_NUTRIENTS_100G and num > 100:
            invalid_fields.append(col)
            invalid_reasons[col] = (
                f"{col}={num} exceeds 100g per 100g product (likely mg/unit confusion)."
            )

    # Cross-field physical sanity checks (impossible ratios invalidate the field and block is_verified_safe)
    if (
        "sugars_100g" in parsed_nums
        and "carbohydrates_100g" in parsed_nums
        and parsed_nums["sugars_100g"] > parsed_nums["carbohydrates_100g"] + 0.5
    ):
        invalid_fields.append("sugars_100g")
        invalid_reasons["sugars_100g"] = (
            f"Sugars ({parsed_nums['sugars_100g']}g) exceed total carbohydrates ({parsed_nums['carbohydrates_100g']}g)."
        )
    if (
        "saturated_fat_100g" in parsed_nums
        and "fat_100g" in parsed_nums
        and parsed_nums["saturated_fat_100g"] > parsed_nums["fat_100g"] + 0.5
    ):
        invalid_fields.append("saturated_fat_100g")
        invalid_reasons["saturated_fat_100g"] = (
            f"Saturated fat ({parsed_nums['saturated_fat_100g']}g) exceeds total fat ({parsed_nums['fat_100g']}g)."
        )

    # Priority classification
    has_tier1_gap = any(f in TIER_1_SAFETY for f in [*missing_fields, *invalid_fields])
    has_tier2_invalid = any(f in TIER_2_NUTRITION for f in invalid_fields)
    has_missing_name = "product_name" in missing_fields or "product_name" in invalid_fields
    has_tier2_missing = any(f in TIER_2_NUTRITION for f in missing_fields)

    if has_tier1_gap or has_tier2_invalid or has_missing_name:
        priority: PriorityLevel = "HIGH"
    elif has_tier2_missing:
        priority = "MEDIUM"
    elif missing_fields or invalid_fields:
        priority = "LOW"
    else:
        priority = "NONE"

    comp_pct, _ = parse_clean_float(row.get("nutrition_completeness_pct"))

    return CsvAuditRecord(
        row_index=row_index,
        code=code,
        product_name=product_name,
        brands=brands,
        missing_fields=missing_fields,
        invalid_fields=invalid_fields,
        invalid_reasons=invalid_reasons,
        warnings=warnings,
        nutrition_completeness_pct=comp_pct,
        baseline_priority=priority,
        needs_llm_review=priority != "NONE",
    )


def audit_csv_file(csv_path: Path) -> CsvDatabaseAuditReport:
    """Load a CSV database and run deterministic completeness & validity checks."""
    df = pd.read_csv(csv_path, dtype={"code": str})
    records = df.to_dict(orient="records")
    results = [audit_csv_row(idx, rec) for idx, rec in enumerate(records)]

    priority_counts: dict[PriorityLevel, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "NONE": 0}
    missing_field_counts: dict[str, int] = {}
    invalid_field_counts: dict[str, int] = {}

    for res in results:
        priority_counts[res.baseline_priority] += 1
        for f in res.missing_fields:
            missing_field_counts[f] = missing_field_counts.get(f, 0) + 1
        for f in res.invalid_fields:
            invalid_field_counts[f] = invalid_field_counts.get(f, 0) + 1

    unique_codes = int(df["code"].nunique(dropna=True)) if "code" in df.columns else len(results)
    duplicate_rows = len(results) - unique_codes
    zero_nutrition_rows = (
        int((df["nutrition_fields_present"].fillna(0) == 0).sum())
        if "nutrition_fields_present" in df.columns
        else 0
    )
    avg_comp = (
        round(float(df["nutrition_completeness_pct"].dropna().mean()), 2)
        if "nutrition_completeness_pct" in df.columns
        and not df["nutrition_completeness_pct"].dropna().empty
        else 0.0
    )

    needing_review = sum(1 for r in results if r.needs_llm_review)
    summary = CsvAuditSummary(
        total_rows=len(results),
        unique_codes=unique_codes,
        duplicate_rows=duplicate_rows,
        records_needing_llm_review=needing_review,
        records_short_circuited=len(results) - needing_review,
        priority_counts=priority_counts,
        missing_field_counts=dict(
            sorted(missing_field_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        invalid_field_counts=dict(
            sorted(invalid_field_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        zero_nutrition_rows=zero_nutrition_rows,
        avg_nutrition_completeness_pct=avg_comp,
    )

    return CsvDatabaseAuditReport(
        source_file=str(csv_path),
        summary=summary,
        results=results,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a food product CSV database.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parent / "demo_subset.csv",
        help="Path to the food CSV database.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the database-wide summary and sample flagged anomalies.",
    )
    args = parser.parse_args()

    report = audit_csv_file(args.input)
    if args.summary_only:
        flagged_examples = [
            r.model_dump() for r in report.results if r.invalid_fields or r.warnings
        ][:10]
        output = {
            "source_file": report.source_file,
            "zero_hallucination_mode": report.zero_hallucination_mode,
            "summary": report.summary.model_dump(),
            "sample_invalid_or_warning_records": flagged_examples,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
