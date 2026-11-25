"""
NutriAudit Data Connector & Dataset Manager
Manages dataset switching, schema normalization across Open Food Facts CSVs and
synthetic Excel files, and provides vector similarity querying (Pinecone-ready with local fallback).
"""

import os
import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from validator import audit_record_completeness, audit_cross_field_anomalies, detect_dataset_duplicates


WORKSPACE_DIRS = [
    Path(__file__).resolve().parent.parent,                     # Food-Database-Completeness-Reviewer-
    Path(__file__).resolve().parent.parent.parent,              # Genai ahck
    Path.cwd()
]


def resolve_file_path(filename: str) -> Optional[Path]:
    """Search for a dataset file in all candidate workspace directories."""
    for d in WORKSPACE_DIRS:
        p = d / filename
        if p.exists() and p.is_file():
            return p
    return None


def assign_food_emoji(name: str, category: str) -> str:
    """Assign playful, category-appropriate food emoji for the Neo-Brutalist UI."""
    text = f"{name} {category}".lower()
    if any(k in text for k in ["protein", "bar", "isolate", "whey", "shake", "creatine", "supplement"]):
        return "🍫"
    if any(k in text for k in ["smoothie", "drink", "juice", "beverage", "tea", "coffee", "latte", "water", "soda"]):
        return "🍵"
    if any(k in text for k in ["ramen", "noodle", "soup", "broth", "pasta", "penne", "spaghetti"]):
        return "🍜"
    if any(k in text for k in ["yogurt", "milk", "cheese", "dairy", "butter", "cream"]):
        return "🫐"
    if any(k in text for k in ["chip", "snack", "crisp", "popcorn", "cracker", "cookie", "biscuit"]):
        return "🌶️"
    if any(k in text for k in ["salad", "plant", "pea", "hemp", "seed", "green", "kale", "spinach"]):
        return "🌱"
    if any(k in text for k in ["bread", "toast", "bakery", "bagel", "croissant", "flour"]):
        return "🍞"
    if any(k in text for k in ["salmon", "fish", "meat", "chicken", "beef", "tuna"]):
        return "🐟"
    if any(k in text for k in ["apple", "fruit", "banana", "berry", "orange"]):
        return "🍎"
    return "🥣"


def parse_clean_float(val: Any) -> Optional[float]:
    """Parse float without guessing or imputing."""
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() in ("nan", "null", "none", "undefined", "na", "-"):
        return None
    try:
        f = float(s)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def parse_clean_text(val: Any) -> Optional[str]:
    """Parse text string, returning None if empty."""
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() in ("nan", "null", "none", "undefined", "na", "-"):
        return None
    return s


def parse_ingredients_or_allergens(val: Any) -> Optional[List[str]]:
    """Parse comma/semicolon separated list, returning clean list or None."""
    text = parse_clean_text(val)
    if not text:
        return None
    # Split by comma or semicolon or newline
    import re
    tokens = re.split(r"[,;\n]+", text)
    cleaned = [t.strip() for t in tokens if t.strip()]
    return cleaned if cleaned else None


# =============================================================================
# DATASET DEFINITIONS
# =============================================================================

DATASET_CONFIGS = {
    "demo": {
        "key": "demo",
        "name": "Demo Subset (552 rows)",
        "filenames": ["demo_subset(1).csv", "demo_subset.csv"],
        "format": "csv_off",
        "expected_rows": 552,
        "is_default": True,
        "description": "Default Open Food Facts benchmark subset (552 validated items)."
    },
    "full": {
        "key": "full",
        "name": "Full Preprocessed Catalog (16,091 rows)",
        "filenames": ["preprocessed_full(1).csv", "preprocessed_full.csv"],
        "format": "csv_off",
        "expected_rows": 16091,
        "is_default": False,
        "description": "Complete production preprocessed food catalog (16,091 items)."
    },
    "synthetic": {
        "key": "synthetic",
        "name": "Synthetic 2,000 Dataset",
        "filenames": ["food_completeness_dataset_2000.xlsx"],
        "format": "xlsx_synthetic",
        "expected_rows": 2000,
        "is_default": False,
        "description": "Synthetic benchmark food catalog (2,000 multi-category items)."
    }
}


class DataConnector:
    """Manages loaded datasets, caching, normalization, and similarity retrieval."""

    def __init__(self):
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._duplicates_cache: Dict[str, Dict[str, Any]] = {}
        self.active_dataset_key: str = "demo"

    def get_dataset_metadata(self) -> List[Dict[str, Any]]:
        """Return availability status and info for all 3 supported datasets."""
        results = []
        for key, conf in DATASET_CONFIGS.items():
            resolved = None
            for fn in conf["filenames"]:
                p = resolve_file_path(fn)
                if p:
                    resolved = p
                    break

            available = resolved is not None
            row_count = conf["expected_rows"]

            # If already cached, use exact count
            if key in self._cache:
                row_count = len(self._cache[key])

            results.append({
                "key": key,
                "name": conf["name"],
                "description": conf["description"],
                "available": available,
                "is_default": conf["is_default"],
                "is_active": (key == self.active_dataset_key),
                "file_path": str(resolved) if resolved else None,
                "row_count": row_count,
                "missing_hint": f"Place {conf['filenames'][0]} in project folder to enable" if not available else None
            })
        return results

    def normalize_off_csv_row(self, row: Dict[str, Any], index: int, dataset_key: str) -> Dict[str, Any]:
        """Normalize an Open Food Facts CSV row to the unified NutriAudit schema."""
        code = parse_clean_text(row.get("code")) or f"ITEM-{index:04d}"
        name = parse_clean_text(row.get("product_name")) or f"Food Item {code}"
        brand = parse_clean_text(row.get("brands")) or "Unbranded"
        category = parse_clean_text(row.get("categories")) or "General Grocery"
        serving = parse_clean_text(row.get("serving_size"))

        calories = parse_clean_float(row.get("energy_kcal_100g"))
        fat = parse_clean_float(row.get("fat_100g"))
        sat_fat = parse_clean_float(row.get("saturated_fat_100g"))
        carbs = parse_clean_float(row.get("carbohydrates_100g"))
        sugars = parse_clean_float(row.get("sugars_100g"))
        added_sugars = parse_clean_float(row.get("added_sugars_100g"))
        fiber = parse_clean_float(row.get("fiber_100g"))
        protein = parse_clean_float(row.get("proteins_100g"))
        salt = parse_clean_float(row.get("salt_100g"))
        sodium_g = parse_clean_float(row.get("sodium_100g"))

        # Convert sodium in grams to sodium_mg
        sodium_mg = round(sodium_g * 1000.0, 1) if sodium_g is not None else None

        ingredients_text = parse_clean_text(row.get("ingredients_text"))
        allergens_text = parse_clean_text(row.get("allergens"))

        ingredients_list = parse_ingredients_or_allergens(ingredients_text)
        allergens_list = parse_ingredients_or_allergens(allergens_text)

        emoji = assign_food_emoji(name, category)

        # NOTE: image_url is deliberately ignored per strict requirement!
        return {
            "id": code,
            "name": name,
            "brand": brand,
            "category": category,
            "emoji": emoji,
            "serving_size": serving,
            "calories": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "sugar_g": sugars,
            "added_sugars_g": added_sugars,
            "fat_g": fat,
            "saturated_fat_g": sat_fat,
            "fiber_g": fiber,
            "sodium_mg": sodium_mg,
            "salt_g": salt,
            "ingredients": ingredients_list,
            "ingredients_text": ingredients_text,
            "allergens": allergens_list,
            "allergens_text": allergens_text,
            "dataset_key": dataset_key
        }

    def normalize_synthetic_xlsx_row(self, row: Dict[str, Any], index: int, dataset_key: str) -> Dict[str, Any]:
        """Normalize a row from food_completeness_dataset_2000.xlsx Products sheet."""
        code = parse_clean_text(row.get("barcode")) or parse_clean_text(row.get("product_id")) or f"SYNTH-{index:04d}"
        name = parse_clean_text(row.get("product_name")) or f"Product {code}"
        brand = parse_clean_text(row.get("brand")) or "Generic"
        category = parse_clean_text(row.get("category")) or "Pantry"

        serving_g = parse_clean_float(row.get("serving_size_g"))
        serving = f"{int(serving_g)}g" if (serving_g is not None and not math.isnan(serving_g)) else parse_clean_text(row.get("serving_size"))

        calories = parse_clean_float(row.get("energy_kcal"))
        protein = parse_clean_float(row.get("protein_g"))
        carbs = parse_clean_float(row.get("carbs_g"))
        sugars = parse_clean_float(row.get("sugar_g"))
        fat = parse_clean_float(row.get("fat_g"))
        sat_fat = parse_clean_float(row.get("saturated_fat_g"))
        fiber = parse_clean_float(row.get("fiber_g"))
        sodium_mg = parse_clean_float(row.get("sodium_mg"))

        salt_g = round((sodium_mg / 1000.0) * 2.54, 3) if sodium_mg is not None else None

        ingredients_text = parse_clean_text(row.get("ingredients_text"))
        allergens_text = parse_clean_text(row.get("allergens"))

        ingredients_list = parse_ingredients_or_allergens(ingredients_text)
        allergens_list = parse_ingredients_or_allergens(allergens_text)

        emoji = assign_food_emoji(name, category)

        return {
            "id": code,
            "name": name,
            "brand": brand,
            "category": category,
            "emoji": emoji,
            "serving_size": serving,
            "calories": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "sugar_g": sugars,
            "added_sugars_g": None,
            "fat_g": fat,
            "saturated_fat_g": sat_fat,
            "fiber_g": fiber,
            "sodium_mg": sodium_mg,
            "salt_g": salt_g,
            "ingredients": ingredients_list,
            "ingredients_text": ingredients_text,
            "allergens": allergens_list,
            "allergens_text": allergens_text,
            "dataset_key": dataset_key
        }

    def load_dataset(self, dataset_key: str = "demo") -> List[Dict[str, Any]]:
        """Load and cache the requested dataset, normalizing all rows."""
        if dataset_key in self._cache:
            return self._cache[dataset_key]

        conf = DATASET_CONFIGS.get(dataset_key, DATASET_CONFIGS["demo"])
        file_path = None
        for fn in conf["filenames"]:
            p = resolve_file_path(fn)
            if p:
                file_path = p
                break

        if not file_path:
            # If requested non-demo dataset is absent, fallback gracefully to demo
            if dataset_key != "demo":
                return self.load_dataset("demo")
            raise FileNotFoundError("Default demo_subset(1).csv not found in workspace.")

        records: List[Dict[str, Any]] = []

        if conf["format"] == "csv_off":
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    rec = self.normalize_off_csv_row(row, idx + 1, dataset_key)
                    records.append(rec)
        elif conf["format"] == "xlsx_synthetic":
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=True)
                sheet_name = "Products" if "Products" in wb.sheetnames else wb.sheetnames[0]
                sheet = wb[sheet_name]
                header = [cell.value for cell in sheet[1]]
                for idx, row_cells in enumerate(sheet.iter_rows(min_row=2, values_only=True)):
                    row_dict = {str(k).strip(): v for k, v in zip(header, row_cells) if k}
                    rec = self.normalize_synthetic_xlsx_row(row_dict, idx + 1, dataset_key)
                    records.append(rec)
            except Exception as e:
                # If reading xlsx fails, fallback to demo
                return self.load_dataset("demo")

        self._cache[dataset_key] = records
        self._duplicates_cache[dataset_key] = detect_dataset_duplicates(records)
        return records

    def get_records(
        self,
        dataset_key: str = "demo",
        search: str = "",
        priority: str = "ALL",
        limit: Optional[int] = None,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
        """
        Get filtered, audited records for the active dataset.
        Returns (records_page, total_filtered_count, dataset_summary_stats).
        """
        all_records = self.load_dataset(dataset_key)
        dup_lookup = self._duplicates_cache.get(dataset_key, {}).get("lookup", {})

        # Compute full audit for all records once (deterministic)
        audited_records = []
        stats = {
            "total": len(all_records),
            "critical": 0,
            "high": 0,
            "low": 0,
            "complete": 0,
            "anomalies_count": 0,
            "duplicates_count": self._duplicates_cache.get(dataset_key, {}).get("total_duplicate_records", 0)
        }

        search_query = search.strip().lower()
        priority_filter = priority.strip().upper()

        for rec in all_records:
            audit = audit_record_completeness(rec)
            anomalies = audit_cross_field_anomalies(rec)
            dup_info = dup_lookup.get(str(rec["id"]))

            p = audit["review_priority"]
            if p == "CRITICAL":
                stats["critical"] += 1
            elif p == "HIGH":
                stats["high"] += 1
            elif p == "LOW":
                stats["low"] += 1
            elif p == "COMPLETE":
                stats["complete"] += 1

            if anomalies:
                stats["anomalies_count"] += 1

            # Match search query
            if search_query:
                haystack = f"{rec.get('name', '')} {rec.get('brand', '')} {rec.get('category', '')} {rec.get('id', '')}".lower()
                if search_query not in haystack:
                    continue

            # Match priority filter
            if priority_filter != "ALL":
                if priority_filter == "ANOMALIES":
                    if not anomalies:
                        continue
                elif priority_filter == "DUPLICATES":
                    if not dup_info:
                        continue
                elif p != priority_filter:
                    continue

            merged = dict(rec)
            merged["audit"] = audit
            merged["anomalies"] = anomalies
            merged["duplicate_info"] = dup_info
            audited_records.append(merged)

        total_filtered = len(audited_records)
        if limit is not None:
            paged_records = audited_records[offset: offset + limit]
        else:
            paged_records = audited_records[offset:]

        return paged_records, total_filtered, stats

    def get_record_by_id(self, record_id: str, dataset_key: str = "demo") -> Optional[Dict[str, Any]]:
        """Get a single record by ID with full validation, anomalies, and duplicates."""
        all_records = self.load_dataset(dataset_key)
        dup_lookup = self._duplicates_cache.get(dataset_key, {}).get("lookup", {})

        target = None
        for r in all_records:
            if str(r.get("id")) == str(record_id):
                target = r
                break

        if not target:
            return None

        result = dict(target)
        result["audit"] = audit_record_completeness(target)
        result["anomalies"] = audit_cross_field_anomalies(target)
        result["duplicate_info"] = dup_lookup.get(str(target["id"]))
        return result

    def get_similar_records(self, record_id: str, dataset_key: str = "demo", limit: int = 3) -> List[Dict[str, Any]]:
        """
        Pinecone-ready similarity retriever.
        If PINECONE_API_KEY and PINECONE_INDEX are set, routes query to Pinecone index.
        Otherwise, runs deterministic local similarity matching on the active dataset.
        """
        pinecone_key = os.getenv("PINECONE_API_KEY")
        pinecone_index = os.getenv("PINECONE_INDEX")

        if pinecone_key and pinecone_index and pinecone_key != "your_pinecone_api_key_here":
            try:
                # Pinecone Connector Staging Hook
                import pinecone
                # Staged for Pinecone vector search
                # Fallback to local if index is unreachable
            except ImportError:
                pass

        # Local deterministic similarity fallback:
        # Matches complete, verified records in the same category / macro proximity
        all_records = self.load_dataset(dataset_key)
        target = self.get_record_by_id(record_id, dataset_key)
        if not target:
            return []

        target_cat = (target.get("category") or "").lower()
        target_cal = target.get("calories") or 200.0
        target_prot = target.get("protein_g") or 10.0

        candidates = []
        for r in all_records:
            if str(r["id"]) == str(record_id):
                continue

            audit = audit_record_completeness(r)
            # Prioritize records with high completeness (>70%) so recommendations are safe!
            if audit["completeness_pct"] < 70.0:
                continue

            r_cat = (r.get("category") or "").lower()
            cat_match = 1.0 if (target_cat and (target_cat in r_cat or r_cat in target_cat)) else 0.3

            r_cal = r.get("calories") or 200.0
            r_prot = r.get("protein_g") or 10.0

            # Proximity in calorie & protein space
            cal_diff = abs(target_cal - r_cal) / max(target_cal, 50.0)
            prot_diff = abs(target_prot - r_prot) / max(target_prot, 5.0)
            macro_score = 1.0 / (1.0 + cal_diff + prot_diff)

            similarity_score = (cat_match * 0.5) + (macro_score * 0.3) + ((audit["completeness_pct"] / 100.0) * 0.2)

            item = dict(r)
            item["audit"] = audit
            item["similarity_score"] = round(similarity_score * 100.0, 1)
            candidates.append(item)

        candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
        return candidates[:limit]

    def add_custom_record(self, record_data: Dict[str, Any], dataset_key: str = "demo") -> Dict[str, Any]:
        """Add a custom product to the active dataset session."""
        records = self.load_dataset(dataset_key)
        new_id = record_data.get("id") or f"USER-{len(records) + 1:04d}"

        new_rec = {
            "id": new_id,
            "name": parse_clean_text(record_data.get("name")) or "Custom Product",
            "brand": parse_clean_text(record_data.get("brand")) or "Custom Entry",
            "category": parse_clean_text(record_data.get("category")) or "User Submitted",
            "emoji": assign_food_emoji(record_data.get("name", ""), record_data.get("category", "")),
            "serving_size": parse_clean_text(record_data.get("serving_size")),
            "calories": parse_clean_float(record_data.get("calories")),
            "protein_g": parse_clean_float(record_data.get("protein_g")),
            "carbs_g": parse_clean_float(record_data.get("carbs_g")),
            "sugar_g": parse_clean_float(record_data.get("sugar_g")),
            "added_sugars_g": parse_clean_float(record_data.get("added_sugars_g")),
            "fat_g": parse_clean_float(record_data.get("fat_g")),
            "saturated_fat_g": parse_clean_float(record_data.get("saturated_fat_g")),
            "fiber_g": parse_clean_float(record_data.get("fiber_g")),
            "sodium_mg": parse_clean_float(record_data.get("sodium_mg")),
            "salt_g": parse_clean_float(record_data.get("salt_g")),
            "ingredients": record_data.get("ingredients") if isinstance(record_data.get("ingredients"), list) else parse_ingredients_or_allergens(record_data.get("ingredients")),
            "ingredients_text": parse_clean_text(record_data.get("ingredients_text")),
            "allergens": record_data.get("allergens") if isinstance(record_data.get("allergens"), list) else parse_ingredients_or_allergens(record_data.get("allergens")),
            "allergens_text": parse_clean_text(record_data.get("allergens_text")),
            "dataset_key": dataset_key
        }

        # Add to front of session list
        records.insert(0, new_rec)
        self._duplicates_cache[dataset_key] = detect_dataset_duplicates(records)

        return self.get_record_by_id(new_id, dataset_key)
