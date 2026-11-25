"""
NutriAudit Deterministic Completeness & Validation Engine
Strict Zero-Hallucination Contract:
Never invent, estimate, impute, or guess any missing nutritional or ingredient value.
All missing fields are explicitly preserved and labeled as MISSING.
"""

import math
import re
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
        return len(val) == 0 or all(is_missing_value(item) for item in val)
    if isinstance(val, str):
        cleaned = val.strip().lower()
        return cleaned in MISSING_TOKENS
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return not math.isfinite(val)
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
        if isinstance(val, bool) or is_missing_value(val):
            return None
        try:
            num = float(val)
            return num if math.isfinite(num) else None
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


_CHEMICAL_ADDITIVE_PATTERNS: List[Tuple[str, str, str]] = [
    (r"\bE\s?(?:1\d{2}|2\d{2}|3\d{2}|4\d{2}|5\d{2}|6\d{2}|9\d{2}|1[0-5]\d{2})[a-z]?\b", "MEDIUM", "E-number food additive"),
    (r"\b(?:sodium\s+nitrite|sodium\s+nitrate|potassium\s+nitrite|potassium\s+nitrate|e\s?249|e\s?250|e\s?251|e\s?252)\b", "HIGH", "Nitrite/nitrate curing preservative"),
    (r"\b(?:sul[fph]ites?|sulfur\s+dioxide|sulphur\s+dioxide|sodium\s+metabisul[fph]ite|potassium\s+bisul[fph]ite|e\s?22[0-8])\b", "HIGH", "Sulfite preservative (asthma/allergen sensitivity risk)"),
    (r"\b(?:aspartame|acesulfame[\s-]*(?:k|potassium)?|sucralose|saccharin|neotame|e\s?950|e\s?951|e\s?954|e\s?955)\b", "MEDIUM", "Artificial non-nutritive sweetener"),
    (r"\b(?:sodium\s+benzoate|potassium\s+sorbate|benzoic\s+acid|calcium\s+propionate|\bbha\b|\bbht\b|\btbhq\b|e\s?20[0-3]|e\s?21[0-3]|e\s?32[01])\b", "MEDIUM", "Synthetic chemical preservative/antioxidant"),
    (r"\b(?:monosodium\s+glutamate|\bmsg\b|disodium\s+inosinate|disodium\s+guanylate|e\s?62[0-5])\b", "LOW", "Chemical flavor enhancer"),
    (r"\b(?:tartrazine|allura\s+red|sunset\s+yellow|brilliant\s+blue|red\s*#?40|yellow\s*#?[56]|blue\s*#?1|e\s?102|e\s?110|e\s?129|e\s?133)\b", "MEDIUM", "Synthetic azo/food colorant"),
    (r"\b(?:partially\s+hydrogenated|hydrogenated\s+(?:vegetable|palm|soybean|cottonseed)?\s*oil)\b", "HIGH", "Hydrogenated fat (potential industrial trans-fat source)"),
]

_ALLERGEN_INGREDIENT_MAP: Dict[str, Tuple[str, ...]] = {
    "milk": ("milk", "whey", "casein", "caseinate", "lactose", "butter", "buttermilk", "cream", "cheese", "yogurt"),
    "peanuts": ("peanut", "arachis"),
    "tree_nuts": ("almond", "walnut", "cashew", "hazelnut", "pistachio", "pecan", "macadamia", "brazil nut", "pine nut"),
    "soy": ("soy", "soya", "soybean", "tofu", "edamame", "soy lecithin"),
    "wheat_gluten": ("wheat", "gluten", "barley", "rye", "spelt", "semolina", "durum"),
    "eggs": ("egg", "eggs", "albumin", "ovalbumin", "lysozyme"),
    "fish": ("fish", "salmon", "tuna", "cod", "anchovy", "anchovies", "sardine", "mackerel", "trout"),
    "crustaceans": ("shrimp", "prawn", "crab", "lobster", "crayfish", "krill"),
    "sesame": ("sesame", "tahini"),
    "mustard": ("mustard",),
}


def audit_math_and_chemical_checks(record: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Runs deterministic on-demand mathematical and chemical safety checks for Deep Audit
    prompt injection without inventing or imputing missing values.
    """
    base_anomalies = audit_cross_field_anomalies(record)
    math_checks: List[Dict[str, Any]] = []
    chemical_checks: List[Dict[str, Any]] = []

    for a in base_anomalies:
        if a.get("type") in ("sodium_exceeds_salt", "salt_sodium_mismatch"):
            chemical_checks.append(a)
        else:
            math_checks.append(a)

    def get_num(key: str) -> Optional[float]:
        val = record.get(key)
        if isinstance(val, bool) or is_missing_value(val):
            return None
        try:
            num = float(val)
            return num if math.isfinite(num) else None
        except (ValueError, TypeError):
            return None

    calories = get_num("calories")
    protein = get_num("protein_g")
    carbs = get_num("carbs_g")
    fat = get_num("fat_g")
    fiber = get_num("fiber_g") or 0.0

    # Atwater macronutrient energy balance check (4 kcal/g protein & carbs, 9 kcal/g fat)
    if calories is not None and protein is not None and carbs is not None and fat is not None:
        expected_kcal = (4.0 * protein) + (4.0 * carbs) + (9.0 * fat)
        diff_kcal = abs(calories - expected_kcal)
        rel_diff = diff_kcal / max(calories, expected_kcal, 1.0)
        if diff_kcal > 45.0 and rel_diff > 0.30 and abs(calories - (expected_kcal + 2.0 * fiber)) > 45.0:
            math_checks.append({
                "type": "atwater_energy_mismatch",
                "field": "calories",
                "severity": "MEDIUM",
                "message": (
                    f"Atwater energy balance discrepancy: Declared calories ({calories:.1f} kcal) differ from "
                    f"macro-derived estimate (~{expected_kcal:.1f} kcal from 4*P + 4*C + 9*F)."
                ),
            })

    # Combined macronutrient mass sum check (>105g per 100g tolerance)
    if protein is not None and carbs is not None and fat is not None:
        macro_sum = protein + carbs + fat
        if macro_sum > 105.0:
            math_checks.append({
                "type": "macro_sum_exceeds_100g",
                "field": "protein_g,carbs_g,fat_g",
                "severity": "CRITICAL",
                "message": (
                    f"Mass conservation contradiction: Protein ({protein:.1f}g) + Carbs ({carbs:.1f}g) + "
                    f"Fat ({fat:.1f}g) sums to {macro_sum:.1f}g per 100g (exceeds 100g physical mass)."
                ),
            })

    # Chemical & ingredient formulation scan
    raw_ing = record.get("ingredients_text")
    if is_missing_value(raw_ing):
        ing_list = record.get("ingredients")
        if isinstance(ing_list, list) and not is_missing_value(ing_list):
            raw_ing = ", ".join(str(x) for x in ing_list if not is_missing_value(x))
        else:
            raw_ing = None

    raw_alg = record.get("allergens_text")
    if is_missing_value(raw_alg):
        alg_list = record.get("allergens")
        if isinstance(alg_list, list) and not is_missing_value(alg_list):
            raw_alg = ", ".join(str(x) for x in alg_list if not is_missing_value(x))
        else:
            raw_alg = None

    if not raw_ing or is_missing_value(raw_ing):
        chemical_checks.append({
            "type": "chemical_scan_blocked_missing_ingredients",
            "field": "ingredients",
            "severity": "CRITICAL",
            "message": "Ingredient formulation is MISSING: chemical additives, E-numbers, preservatives, and hidden allergens cannot be verified.",
        })
    else:
        ing_str = str(raw_ing)
        ing_lower = ing_str.lower()

        # Scan chemical additives / preservatives / sweeteners / dyes
        for pattern, severity, label in _CHEMICAL_ADDITIVE_PATTERNS:
            matches = sorted({m.group(0).strip() for m in re.finditer(pattern, ing_str, flags=re.IGNORECASE)})
            if matches:
                chemical_checks.append({
                    "type": "chemical_additive_detected",
                    "field": "ingredients",
                    "severity": severity,
                    "message": f"{label} detected in ingredients: {', '.join(matches[:6])}.",
                })

        # Cross-check ingredient keywords against declared allergens
        alg_lower = str(raw_alg or "").lower()
        alg_missing = not raw_alg or is_missing_value(raw_alg)
        for allergen_group, keywords in _ALLERGEN_INGREDIENT_MAP.items():
            matched_kw = [kw for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", ing_lower)]
            if matched_kw:
                group_declared = any(kw in alg_lower for kw in keywords) or allergen_group.replace("_", " ") in alg_lower
                if alg_missing:
                    chemical_checks.append({
                        "type": "allergen_ingredient_undeclared",
                        "field": "allergens",
                        "severity": "CRITICAL",
                        "message": (
                            f"Chemical/allergen hazard: Ingredient text contains '{matched_kw[0]}' ({allergen_group}) "
                            "while Allergens declaration is MISSING."
                        ),
                    })
                elif not group_declared and "none" not in alg_lower:
                    chemical_checks.append({
                        "type": "allergen_ingredient_mismatch",
                        "field": "allergens",
                        "severity": "HIGH",
                        "message": (
                            f"Allergen cross-check alert: Ingredient '{matched_kw[0]}' ({allergen_group}) "
                            f"is present in ingredients but not explicitly listed in allergens ('{raw_alg}')."
                        ),
                    })

    return {
        "math_checks": math_checks,
        "chemical_checks": chemical_checks,
    }
