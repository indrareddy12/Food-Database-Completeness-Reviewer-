"""
NutriAudit Data Connector & Dataset Manager
Manages dataset switching, schema normalization across Open Food Facts CSVs and
synthetic Excel files, and provides vector similarity querying (Pinecone-ready with local fallback).
"""

import os
import re
import csv
import math
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from validator import (
    MISSING_TOKENS,
    audit_record_completeness,
    audit_cross_field_anomalies,
    detect_dataset_duplicates,
)

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger("nutriaudit.connector")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"

WORKSPACE_DIRS = [
    UPLOAD_DIR,                                   # Isolated uploaded files
    PROJECT_ROOT,                                 # Food-Database-Completeness-Reviewer-
    PROJECT_ROOT / "food-db-reviewer",            # Shared demo CSV location if merged
    PROJECT_ROOT.parent,                          # Genai ahck
    Path.cwd()
]


def resolve_file_path(filename: str) -> Optional[Path]:
    """Search for a dataset file in all candidate workspace directories."""
    for d in WORKSPACE_DIRS:
        p = d / filename
        if p.exists() and p.is_file():
            return p
    return None


def assign_food_icon(name: Optional[str], category: Optional[str]) -> Tuple[str, str]:
    """Assign a clean Lucide icon token and Tailwind ink-compatible color class."""
    text = f"{name or ''} {category or ''}".lower()
    if any(k in text for k in ["protein", "bar", "isolate", "whey", "shake", "creatine", "supplement"]):
        if any(k in text for k in ["isolate", "whey", "shake", "milk"]):
            return ("milk", "text-sky-700")
        return ("candy", "text-amber-700")
    if any(k in text for k in ["smoothie", "drink", "juice", "beverage", "tea", "coffee", "latte", "water", "soda"]):
        return ("cup-soda", "text-emerald-700")
    if any(k in text for k in ["ramen", "noodle", "soup", "broth", "pasta", "penne", "spaghetti"]):
        return ("soup", "text-orange-700")
    if any(k in text for k in ["yogurt", "milk", "cheese", "dairy", "butter", "cream"]):
        return ("milk", "text-sky-700")
    if any(k in text for k in ["chip", "snack", "crisp", "popcorn", "cracker", "cookie", "biscuit", "spicy"]):
        return ("flame", "text-red-700")
    if any(k in text for k in ["salad", "plant", "pea", "hemp", "seed", "green", "kale", "spinach"]):
        return ("sprout", "text-emerald-700")
    if any(k in text for k in ["apple", "fruit", "banana", "berry", "orange", "cherry"]):
        return ("cherry", "text-rose-700")
    if any(k in text for k in ["bread", "toast", "bakery", "bagel", "croissant", "flour"]):
        return ("wheat", "text-amber-700")
    if any(k in text for k in ["salmon", "fish", "meat", "chicken", "beef", "tuna"]):
        return ("fish", "text-sky-700")
    return ("utensils", "text-ink")


def parse_clean_float(val: Any) -> Optional[float]:
    """Parse finite float without guessing or imputing."""
    if val is None or isinstance(val, bool):
        return None
    s = str(val).strip()
    if s.lower() in MISSING_TOKENS:
        return None
    try:
        f = float(s)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def parse_clean_text(val: Any) -> Optional[str]:
    """Parse text string, returning None if empty or a placeholder token."""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in MISSING_TOKENS:
        return None
    return s


def parse_ingredients_or_allergens(val: Any) -> Optional[List[str]]:
    """Parse comma/semicolon separated text or list, returning clean list or None."""
    if isinstance(val, (list, tuple)):
        cleaned = [
            str(t).strip()
            for t in val
            if t is not None and str(t).strip() and str(t).strip().lower() not in MISSING_TOKENS
        ]
        return cleaned if cleaned else None
    text = parse_clean_text(val)
    if not text:
        return None
    tokens = re.split(r"[,;\n]+", text)
    cleaned = [t.strip() for t in tokens if t.strip() and t.strip().lower() not in MISSING_TOKENS]
    return cleaned if cleaned else None


# =============================================================================
# DATASET DEFINITIONS
# =============================================================================

DATASET_CONFIGS = {
    "demo": {
        "key": "demo",
        "name": "Demo Subset (552 rows)",
        "filenames": ["demo_subset.csv", "demo_subset(1).csv", "demo_subset1.csv"],
        "format": "csv_off",
        "expected_rows": 552,
        "is_default": True,
        "description": "Default Open Food Facts benchmark subset (552 validated items)."
    },
    "full": {
        "key": "full",
        "name": "Full Preprocessed Catalog (16,091 rows)",
        "filenames": ["preprocessed_full(1).csv", "preprocessed_full1.csv", "preprocessed_full.csv"],
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
        self._pinecone_handle: Optional[Tuple[Any, Any, str, str, str]] = None
        self._pinecone_key_loaded: Optional[str] = None

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
                "missing_hint": f"Place {conf['filenames'][0]} in workspace or upload via UI to enable" if not available else None
            })
        return results

    def normalize_off_csv_row(self, row: Dict[str, Any], index: int, dataset_key: str) -> Dict[str, Any]:
        """
        Normalize an Open Food Facts CSV row to the unified NutriAudit schema.
        Strict Zero-Hallucination Rule: Missing metadata (name, brand, category) and
        nutrients remain None rather than being replaced with synthetic fallback strings.
        """
        code = parse_clean_text(row.get("code")) or f"ITEM-{index:04d}"
        name = parse_clean_text(row.get("product_name"))
        brand = parse_clean_text(row.get("brands"))
        category = parse_clean_text(row.get("categories"))
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

        # Unit conversion only of explicitly declared sodium_100g -> mg
        sodium_mg = round(sodium_g * 1000.0, 1) if sodium_g is not None else None

        ingredients_text = parse_clean_text(row.get("ingredients_text"))
        allergens_text = parse_clean_text(row.get("allergens"))

        ingredients_list = parse_ingredients_or_allergens(ingredients_text)
        allergens_list = parse_ingredients_or_allergens(allergens_text)

        icon, icon_color = assign_food_icon(name, category)

        # NOTE: image_url is deliberately ignored per strict requirement!
        return {
            "id": code,
            "name": name,
            "brand": brand,
            "category": category,
            "icon": icon,
            "iconColor": icon_color,
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
        """
        Normalize a row from food_completeness_dataset_2000.xlsx Products sheet.
        Strict Zero-Hallucination Rule: Missing metadata and absent columns (such as
        salt_g when not present in Excel) remain None and are never derived/imputed.
        """
        code = parse_clean_text(row.get("barcode")) or parse_clean_text(row.get("product_id")) or f"SYNTH-{index:04d}"
        name = parse_clean_text(row.get("product_name"))
        brand = parse_clean_text(row.get("brand"))
        category = parse_clean_text(row.get("category"))

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
        salt_g = parse_clean_float(row.get("salt_g"))  # Do NOT impute salt_g from sodium_mg

        ingredients_text = parse_clean_text(row.get("ingredients_text"))
        allergens_text = parse_clean_text(row.get("allergens"))

        ingredients_list = parse_ingredients_or_allergens(ingredients_text)
        allergens_list = parse_ingredients_or_allergens(allergens_text)

        icon, icon_color = assign_food_icon(name, category)

        return {
            "id": code,
            "name": name,
            "brand": brand,
            "category": category,
            "icon": icon,
            "iconColor": icon_color,
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
        """Load and cache the requested dataset, raising explicit errors if unavailable or malformed."""
        if dataset_key in self._cache:
            return self._cache[dataset_key]

        if dataset_key not in DATASET_CONFIGS:
            raise KeyError(f"Unknown dataset key '{dataset_key}'.")

        conf = DATASET_CONFIGS[dataset_key]
        file_path = None
        for fn in conf["filenames"]:
            p = resolve_file_path(fn)
            if p:
                file_path = p
                break

        if not file_path:
            logger.warning("Requested dataset '%s' file not found (candidates: %s).", dataset_key, conf["filenames"])
            raise FileNotFoundError(
                f"Dataset '{conf['name']}' file ({conf['filenames'][0]}) not found in workspace or uploads."
            )

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
                logger.exception("Failed to parse Excel dataset '%s' at %s: %s", dataset_key, file_path, e)
                raise RuntimeError(f"Failed to read Excel dataset '{file_path.name}': {e}") from e

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

            if search_query:
                haystack = f"{rec.get('name') or ''} {rec.get('brand') or ''} {rec.get('category') or ''} {rec.get('id') or ''}".lower()
                if search_query not in haystack:
                    continue

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

    @staticmethod
    def _get_pinecone_settings() -> Tuple[Optional[str], str, str, str]:
        """Read Pinecone credentials and index config from environment."""
        raw_key = (os.getenv("PINECONE_API_KEY") or "").strip()
        if not raw_key or raw_key == "your_pinecone_api_key_here":
            api_key = None
        else:
            api_key = raw_key
        index_name = (
            os.getenv("PINECONE_INDEX")
            or os.getenv("PINECONE_INDEX_NAME")
            or "food-database-completeness"
        ).strip()
        namespace = (os.getenv("PINECONE_NAMESPACE") or "food-products").strip()
        embed_model = (os.getenv("PINECONE_EMBED_MODEL") or "multilingual-e5-large").strip()
        return api_key, index_name, namespace, embed_model

    def _get_pinecone_handle(self) -> Optional[Tuple[Any, Any, str, str, str]]:
        """Lazily initialize and cache the Pinecone client and Index handle."""
        api_key, index_name, namespace, embed_model = self._get_pinecone_settings()
        if not api_key:
            return None

        if self._pinecone_handle is not None and self._pinecone_key_loaded == api_key:
            return self._pinecone_handle

        from pinecone import Pinecone

        pc = Pinecone(api_key=api_key)
        index = pc.Index(index_name)
        self._pinecone_handle = (pc, index, index_name, namespace, embed_model)
        self._pinecone_key_loaded = api_key
        return self._pinecone_handle

    def get_pinecone_status(self) -> Dict[str, Any]:
        """Return Pinecone connection readiness and live index stats when reachable."""
        api_key, index_name, namespace, embed_model = self._get_pinecone_settings()
        status: Dict[str, Any] = {
            "configured": bool(api_key),
            "sdk_installed": False,
            "connected": False,
            "index_name": index_name,
            "namespace": namespace,
            "embed_model": embed_model,
            "total_vector_count": None,
            "dimension": None,
            "error": None,
        }
        try:
            import pinecone  # noqa: F401
            status["sdk_installed"] = True
        except ImportError as exc:
            status["error"] = f"Pinecone SDK not installed: {exc}"
            return status

        if not api_key:
            return status

        try:
            handle = self._get_pinecone_handle()
            if handle:
                _, index, _, _, _ = handle
                stats = index.describe_index_stats()
                status["connected"] = True
                status["total_vector_count"] = getattr(stats, "total_vector_count", None)
                status["dimension"] = getattr(stats, "dimension", None)
        except Exception as exc:
            logger.warning("Pinecone stats check failed: %s", exc)
            status["error"] = str(exc)

        return status

    @staticmethod
    def _parse_pinecone_text_fields(text: str) -> Dict[str, Any]:
        """Extract only explicitly serialized factual fields from Pinecone vector text."""
        extracted: Dict[str, Any] = {}
        if not text:
            return extracted
        for segment in text.split(" | "):
            if segment.startswith("Serving Size: "):
                val = parse_clean_text(segment[len("Serving Size: "):])
                if val:
                    extracted["serving_size"] = val
            elif segment.startswith("Ingredients: "):
                raw_ing = segment[len("Ingredients: "):].strip()
                if raw_ing and not raw_ing.upper().startswith("MISSING"):
                    extracted["ingredients_text"] = raw_ing
                    extracted["ingredients"] = parse_ingredients_or_allergens(raw_ing)
            elif segment.startswith("Nutrition per 100g: "):
                raw_nut = segment[len("Nutrition per 100g: "):].strip()
                if raw_nut and not raw_nut.upper().startswith("MISSING"):
                    for pair in raw_nut.split(","):
                        if "=" not in pair:
                            continue
                        k, v = pair.strip().split("=", 1)
                        num = parse_clean_float(v)
                        if num is not None:
                            extracted[k.strip()] = num
        return extracted

    def _build_record_from_pinecone_match(
        self,
        match: Any,
        local_lookup: Dict[str, Dict[str, Any]],
        dataset_key: str,
    ) -> Dict[str, Any]:
        """Normalize a Pinecone vector hit using local data or verified Pinecone metadata."""
        match_id = str(match["id"] if isinstance(match, dict) else getattr(match, "id", ""))
        score = float(match["score"] if isinstance(match, dict) else getattr(match, "score", 0.0))
        meta = (match["metadata"] if isinstance(match, dict) else getattr(match, "metadata", None)) or {}
        code = str(meta.get("code") or match_id)

        local_rec = local_lookup.get(code) or local_lookup.get(match_id)
        if local_rec:
            item = dict(local_rec)
            item["audit"] = audit_record_completeness(local_rec)
            item["similarity_score"] = round(score * 100.0, 1)
            item["retrieval_source"] = "pinecone"
            return item

        parsed_text = self._parse_pinecone_text_fields(str(meta.get("text") or ""))
        name = parse_clean_text(meta.get("product_name"))
        brand = parse_clean_text(meta.get("brands"))
        category = parse_clean_text(meta.get("categories"))
        allergens_text = parse_clean_text(meta.get("allergens"))
        allergens_list = parse_ingredients_or_allergens(allergens_text)
        sodium_100g = parse_clean_float(meta.get("sodium_100g"))
        if sodium_100g is None:
            sodium_100g = parsed_text.get("sodium_100g")
        sodium_mg = round(sodium_100g * 1000.0, 1) if sodium_100g is not None else None
        icon, icon_color = assign_food_icon(name, category)

        rec = {
            "id": code,
            "name": name,
            "brand": brand,
            "category": category,
            "icon": icon,
            "iconColor": icon_color,
            "serving_size": parsed_text.get("serving_size"),
            "calories": parse_clean_float(meta.get("energy_kcal_100g")) if meta.get("energy_kcal_100g") is not None else parsed_text.get("energy_kcal_100g"),
            "protein_g": parse_clean_float(meta.get("proteins_100g")) if meta.get("proteins_100g") is not None else parsed_text.get("proteins_100g"),
            "carbs_g": parsed_text.get("carbohydrates_100g"),
            "sugar_g": parse_clean_float(meta.get("sugars_100g")) if meta.get("sugars_100g") is not None else parsed_text.get("sugars_100g"),
            "added_sugars_g": parsed_text.get("added_sugars_100g"),
            "fat_g": parsed_text.get("fat_100g"),
            "saturated_fat_g": parsed_text.get("saturated_fat_100g"),
            "fiber_g": parse_clean_float(meta.get("fiber_100g")) if meta.get("fiber_100g") is not None else parsed_text.get("fiber_100g"),
            "sodium_mg": sodium_mg,
            "salt_g": parsed_text.get("salt_100g"),
            "ingredients": parsed_text.get("ingredients"),
            "ingredients_text": parsed_text.get("ingredients_text"),
            "allergens": allergens_list,
            "allergens_text": allergens_text,
            "dataset_key": dataset_key,
            "pinecone_verified_safe": bool(meta.get("is_verified_safe")),
            "pinecone_priority": meta.get("audit_priority") or meta.get("review_priority"),
        }
        rec["audit"] = audit_record_completeness(rec)
        rec["similarity_score"] = round(score * 100.0, 1)
        rec["retrieval_source"] = "pinecone"
        return rec

    def query_pinecone_similar(
        self,
        query_text: str,
        exclude_id: Optional[str] = None,
        limit: int = 3,
        safe_only: bool = True,
        dataset_key: str = "demo",
    ) -> List[Dict[str, Any]]:
        """Query live Pinecone index via inference embeddings + verified-safe metadata filter."""
        handle = self._get_pinecone_handle()
        if not handle or not query_text.strip():
            return []

        pc, index, _, namespace, embed_model = handle
        embed_resp = pc.inference.embed(
            model=embed_model,
            inputs=[query_text.strip()],
            parameters={"input_type": "query", "truncate": "END"},
        )
        q_vec = embed_resp.data[0]["values"]
        meta_filter = {"is_verified_safe": {"$eq": True}} if safe_only else None
        query_resp = index.query(
            namespace=namespace,
            vector=q_vec,
            top_k=max(limit + 3, 6),
            include_metadata=True,
            filter=meta_filter,
        )

        local_lookup: Dict[str, Dict[str, Any]] = {}
        for cached_list in (self._cache.get(dataset_key), self._cache.get("full")):
            if cached_list:
                for rec in cached_list:
                    local_lookup.setdefault(str(rec.get("id")), rec)

        matches = query_resp.get("matches", []) if isinstance(query_resp, dict) else getattr(query_resp, "matches", []) or []
        results: List[Dict[str, Any]] = []
        for match in matches:
            item = self._build_record_from_pinecone_match(match, local_lookup, dataset_key)
            if exclude_id is not None and str(item.get("id")) == str(exclude_id):
                continue
            if safe_only and item["audit"]["completeness_pct"] < 70.0:
                continue
            results.append(item)
            if len(results) >= limit:
                break

        return results

    def get_similar_records(self, record_id: str, dataset_key: str = "demo", limit: int = 3) -> List[Dict[str, Any]]:
        """
        Pinecone-integrated similarity retriever with safe local fallback.
        Queries Pinecone vector index when configured & reachable; otherwise runs
        deterministic local similarity matching on the active dataset.
        """
        all_records = self.load_dataset(dataset_key)
        target = self.get_record_by_id(record_id, dataset_key)
        if not target:
            return []

        api_key, index_name, _, _ = self._get_pinecone_settings()
        if api_key:
            query_parts = [
                str(target.get("name") or "").strip(),
                str(target.get("category") or "").strip(),
                str(target.get("brand") or "").strip(),
            ]
            query_text = " ".join(p for p in query_parts if p)
            if query_text:
                try:
                    pinecone_matches = self.query_pinecone_similar(
                        query_text=query_text,
                        exclude_id=str(record_id),
                        limit=limit,
                        safe_only=True,
                        dataset_key=dataset_key,
                    )
                    if pinecone_matches:
                        logger.info("Pinecone returned %d verified matches from '%s'.", len(pinecone_matches), index_name)
                        return pinecone_matches
                except ImportError as exc:
                    logger.warning("PINECONE_API_KEY configured but pinecone package is unavailable (%s); falling back to local similarity.", exc)
                except Exception as exc:
                    logger.warning("Pinecone similarity lookup failed (%s); falling back to local similarity.", exc)

        target_cat = (target.get("category") or "").lower()
        target_cal = target.get("calories") or 200.0
        target_prot = target.get("protein_g") or 10.0

        candidates = []
        for r in all_records:
            if str(r["id"]) == str(record_id):
                continue

            audit = audit_record_completeness(r)
            if audit["completeness_pct"] < 70.0:
                continue

            r_cat = (r.get("category") or "").lower()
            cat_match = 1.0 if (target_cat and (target_cat in r_cat or r_cat in target_cat)) else 0.3

            r_cal = r.get("calories") or 200.0
            r_prot = r.get("protein_g") or 10.0

            cal_diff = abs(target_cal - r_cal) / max(target_cal, 50.0)
            prot_diff = abs(target_prot - r_prot) / max(target_prot, 5.0)
            macro_score = 1.0 / (1.0 + cal_diff + prot_diff)

            similarity_score = (cat_match * 0.5) + (macro_score * 0.3) + ((audit["completeness_pct"] / 100.0) * 0.2)

            item = dict(r)
            item["audit"] = audit
            item["similarity_score"] = round(similarity_score * 100.0, 1)
            item["retrieval_source"] = "local_fallback"
            candidates.append(item)

        candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
        return candidates[:limit]

    def add_custom_record(self, record_data: Dict[str, Any], dataset_key: str = "demo") -> Dict[str, Any]:
        """Add a custom product to the active dataset session without inventing missing values."""
        records = self.load_dataset(dataset_key)
        new_id = record_data.get("id") or f"USER-{len(records) + 1:04d}"

        name = parse_clean_text(record_data.get("name"))
        brand = parse_clean_text(record_data.get("brand"))
        category = parse_clean_text(record_data.get("category")) or "Custom Audit"
        icon, icon_color = ("salad", "text-emerald-700")

        new_rec = {
            "id": new_id,
            "name": name,
            "brand": brand,
            "category": category,
            "icon": icon,
            "iconColor": icon_color,
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
            "ingredients": parse_ingredients_or_allergens(record_data.get("ingredients")),
            "ingredients_text": parse_clean_text(record_data.get("ingredients_text")),
            "allergens": parse_ingredients_or_allergens(record_data.get("allergens")),
            "allergens_text": parse_clean_text(record_data.get("allergens_text")),
            "dataset_key": dataset_key
        }

        records.insert(0, new_rec)
        self._duplicates_cache[dataset_key] = detect_dataset_duplicates(records)

        return self.get_record_by_id(new_id, dataset_key)

    def find_mentioned_record(self, text: str, dataset_key: str = "demo") -> Optional[Dict[str, Any]]:
        """Resolve an explicitly mentioned product ID/barcode or product name from user chat text."""
        if not text or not text.strip():
            return None

        cleaned = text.strip()
        records = self.load_dataset(dataset_key)

        # 1. Check explicit IDs / barcodes (e.g., 3267460030306, PROD-101, SYN-100, USER-0001)
        id_candidates = re.findall(r"\b(?:PROD-\d+|SYN-\d+|USER-\d+|\d{5,14})\b", cleaned, flags=re.IGNORECASE)
        for cand in id_candidates:
            rec = self.get_record_by_id(cand, dataset_key)
            if rec:
                return rec

        # 2. Check direct product name containment (prefer longest exact product name match)
        lowered = cleaned.lower()
        best_match_id: Optional[str] = None
        best_len = 0
        for r in records:
            name = (r.get("name") or "").strip().lower()
            if len(name) >= 4 and name in lowered and len(name) > best_len:
                best_len = len(name)
                best_match_id = str(r["id"])

        if best_match_id:
            return self.get_record_by_id(best_match_id, dataset_key)
        return None
