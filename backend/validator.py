"""
NutriAudit Deterministic Completeness & Validation Engine
Strict Zero-Hallucination Contract:
Never invent, estimate, impute, or guess any missing nutritional or ingredient value.
All missing fields are explicitly preserved and labeled as MISSING.
"""

from typing import Any, Dict, List, Optional, Tuple


CRITICAL_FIELDS = ["ingredients", "allergens"]
HIGH_FIELDS = ["calories", "protein_g", "sugar_g", "sodium_mg"]
LOW_FIELDS = ["carbs_g", "fat_g", "serving_size", "fiber_g"]
ALL_EVALUATED_FIELDS = CRITICAL_FIELDS + HIGH_FIELDS + LOW_FIELDS

MISSING_TOKENS = frozenset({
    "", "null", "none", "nan", "undefined", "missing",
    "unknown", "na", "n/a", "tbd", "-", "?", "[]"
})


def is_missing_value(val: Any) -> bool:
    """Check if a field value is missing without guessing or imputing."""
    if val is None:
        return True
    if isinstance(val, (list, tuple)):
        return len(val) == 0
    if isinstance(val, str):
        cleaned = val.strip().lower()
        return cleaned in MISSING_TOKENS
    if isinstance(val, (int, float)):
        import math
        return math.isnan(val)
    return False


def audit_record_completeness(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform deterministic completeness audit on a single food record.
    Returns completeness metrics, missing field lists, priority rank, and safety dial score.
    """
    missing_critical = []
    missing_high = []
    missing_low = []
    present_fields = {}
    missing_fields = []

    for field in ALL_EVALUATED_FIELDS:
        val = record.get(field)
        if is_missing_value(val):
            missing_fields.append(field)
            if field in CRITICAL_FIELDS:
                missing_critical.append(field)
            elif field in HIGH_FIELDS:
                missing_high.append(field)
            else:
                missing_low.append(field)
        else:
            present_fields[field] = val

    present_count = len(ALL_EVALUATED_FIELDS) - len(missing_fields)
    completeness_pct = round((present_count / len(ALL_EVALUATED_FIELDS)) * 100.0, 1)

    # Review Priority assignment
    if missing_critical:
        review_priority = "CRITICAL"
    elif missing_high:
        review_priority = "HIGH"
    elif missing_low:
        review_priority = "LOW"
    else:
        review_priority = "COMPLETE"

    # Safety Speed Dial (0 - 100)
    # Starts at 100, penalizes missing values based on severity
    score = 100
    score -= len(missing_critical) * 30  # critical missing (e.g. ingredients or allergens)
    score -= len(missing_high) * 10      # high missing (calories, protein, sugar, sodium)
    score -= len(missing_low) * 5        # low missing (carbs, fat, serving_size, fiber)
    safety_score = max(0, min(100, score))

    return {
        "completeness_pct": completeness_pct,
        "present_count": present_count,
        "total_fields": len(ALL_EVALUATED_FIELDS),
        "review_priority": review_priority,
        "safety_score": safety_score,
        "missing_critical": missing_critical,
        "missing_high": missing_high,
        "missing_low": missing_low,
        "missing_fields": missing_fields,
        "present_fields": list(present_fields.keys()),
        # Zero-hallucination verification guarantee
        "zero_hallucination_guarantee": True,
        "imputed_fields_count": 0,
        "guarantee_statement": "Zero-Hallucination Contract Active: No missing ingredients, allergens, or nutrition numbers were inferred, guessed, or imputed."
    }


def audit_cross_field_anomalies(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Deterministically flags numeric and cross-field contradictions:
    - Negative values
    - >100g per 100g macros / salt
    - Energy > 900 kcal/100g
    - Added sugars > total sugars
    - Total sugars > total carbohydrates
    - Saturated fat > total fat
    - Salt / Sodium mismatches (chemical ratio violations)
    """
    anomalies: List[Dict[str, Any]] = []

    def get_num(key: str) -> Optional[float]:
        val = record.get(key)
        if is_missing_value(val):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    calories = get_num("calories")
    protein = get_num("protein_g")
    carbs = get_num("carbs_g")
    sugar = get_num("sugar_g")
    added_sugars = get_num("added_sugars_g")
    fat = get_num("fat_g")
    sat_fat = get_num("saturated_fat_g")
    fiber = get_num("fiber_g")
    sodium_mg = get_num("sodium_mg")
    salt = get_num("salt_g")

    # 1. Negative values check
    numeric_checks = {
        "calories": calories,
        "protein_g": protein,
        "carbs_g": carbs,
        "sugar_g": sugar,
        "added_sugars_g": added_sugars,
        "fat_g": fat,
        "saturated_fat_g": sat_fat,
        "fiber_g": fiber,
        "sodium_mg": sodium_mg,
        "salt_g": salt,
    }
    for field_name, num_val in numeric_checks.items():
        if num_val is not None and num_val < 0:
            anomalies.append({
                "type": "negative_value",
                "field": field_name,
                "severity": "CRITICAL",
                "message": f"Negative value detected for {field_name}: {num_val}. Nutrition values cannot be negative."
            })

    # 2. Macro/Salt > 100g per 100g baseline
    macro_100g_checks = {
        "protein_g": protein,
        "carbs_g": carbs,
        "sugar_g": sugar,
        "added_sugars_g": added_sugars,
        "fat_g": fat,
        "saturated_fat_g": sat_fat,
        "fiber_g": fiber,
        "salt_g": salt,
    }
    for field_name, num_val in macro_100g_checks.items():
        if num_val is not None and num_val > 100.0:
            anomalies.append({
                "type": "macro_exceeds_100g",
                "field": field_name,
                "severity": "CRITICAL",
                "message": f"Physically impossible concentration: {field_name} is declared as {num_val}g per 100g (exceeds 100g ceiling)."
            })

    # 3. Energy > 900 kcal (100g pure fat = 900 kcal)
    if calories is not None and calories > 900.0:
        anomalies.append({
            "type": "excessive_calories",
            "field": "calories",
            "severity": "CRITICAL",
            "message": f"Implausible energy density: {calories} kcal/100g exceeds maximum theoretical dietary density (pure fat yields ~900 kcal/100g)."
        })

    # 4. Added sugars > Total sugars
    if added_sugars is not None and sugar is not None:
        if added_sugars > sugar + 0.05:
            anomalies.append({
                "type": "added_sugars_exceed_sugars",
                "field": "added_sugars_g",
                "severity": "HIGH",
                "message": f"Mathematical contradiction: Added sugars ({added_sugars}g) cannot exceed total sugars ({sugar}g)."
            })

    # 5. Sugars > Total Carbohydrates
    if sugar is not None and carbs is not None:
        if sugar > carbs + 0.05:
            anomalies.append({
                "type": "sugars_exceed_carbs",
                "field": "sugar_g",
                "severity": "HIGH",
                "message": f"Mathematical contradiction: Total sugars ({sugar}g) cannot exceed total carbohydrates ({carbs}g)."
            })

    # 6. Saturated fat > Total Fat
    if sat_fat is not None and fat is not None:
        if sat_fat > fat + 0.05:
            anomalies.append({
                "type": "saturated_fat_exceeds_fat",
                "field": "saturated_fat_g",
                "severity": "HIGH",
                "message": f"Mathematical contradiction: Saturated fat ({sat_fat}g) cannot exceed total fat ({fat}g)."
            })

    # 7. Salt vs Sodium contradictions
    # Chemistry: Salt (NaCl) is ~39.3% Sodium and ~60.7% Chloride by mass.
    # Therefore, Salt (g) ≈ Sodium (g) * 2.54.
    sodium_g = (sodium_mg / 1000.0) if sodium_mg is not None else None
    if sodium_g is not None and salt is not None:
        # Chemical impossibility: Sodium cannot weigh more than total Salt!
        if sodium_g > salt + 0.01:
            anomalies.append({
                "type": "sodium_exceeds_salt",
                "field": "sodium_mg",
                "severity": "CRITICAL",
                "message": f"Chemical impossibility: Declared sodium ({sodium_g:.3f}g) exceeds declared total salt ({salt:.3f}g). Sodium is only a component of salt."
            })
        elif salt > 0.05:
            expected_salt = sodium_g * 2.54
            diff = abs(salt - expected_salt)
            rel_diff = diff / max(salt, 0.01)
            # Flag significant discrepancy (more than 0.2g and >35% difference)
            if diff > 0.2 and rel_diff > 0.35:
                anomalies.append({
                    "type": "salt_sodium_mismatch",
                    "field": "salt_g",
                    "severity": "MEDIUM",
                    "message": f"Chemical ratio mismatch: Declared salt is {salt:.2f}g, but declared sodium ({sodium_g:.3f}g) corresponds to ~{expected_salt:.2f}g salt."
                })

    return anomalies


def detect_dataset_duplicates(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Detects duplicate (product_name, brand) pairs across a list of normalized records.
    Returns a lookup dictionary mapping record ID -> duplicate info.
    """
    groups: Dict[Tuple[str, str], List[str]] = {}
    for r in records:
        r_id = str(r.get("id", ""))
        name = (r.get("name") or "").strip().lower()
        brand = (r.get("brand") or "").strip().lower()
        if name:
            key = (name, brand)
            groups.setdefault(key, []).append(r_id)

    duplicates_lookup: Dict[str, Dict[str, Any]] = {}
    total_duplicate_items = 0

    for key, ids in groups.items():
        if len(ids) > 1:
            total_duplicate_items += len(ids)
            for r_id in ids:
                other_ids = [i for i in ids if i != r_id]
                duplicates_lookup[r_id] = {
                    "is_duplicate": True,
                    "duplicate_count": len(ids),
                    "duplicate_of": other_ids,
                    "duplicate_name": key[0],
                    "duplicate_brand": key[1]
                }

    return {
        "lookup": duplicates_lookup,
        "duplicate_groups_count": sum(1 for ids in groups.values() if len(ids) > 1),
        "total_duplicate_records": total_duplicate_items
    }
