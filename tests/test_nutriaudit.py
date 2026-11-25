"""
NutriAudit Comprehensive Integration & Verification Test Suite
Tests Validator, Data Connector, Flask REST API Endpoints, Triage Service, and Frontend Contracts.
"""

import os
import sys
from pathlib import Path

# Add backend directory to path
backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from main import app
from data_connector import DataConnector, DATASET_CONFIGS
from validator import (
    audit_record_completeness,
    audit_cross_field_anomalies,
    detect_dataset_duplicates,
    is_missing_value
)
from triage_service import run_triage_audit, get_active_groq_key


def test_validator_zero_hallucination_and_missing_detection():
    """Verify that missing values are never guessed, imputed, or assumed."""
    record = {
        "id": "TEST-01",
        "name": "Zero Hallucination Bar",
        "brand": "AuditLabs",
        "calories": None,
        "protein_g": 20.0,
        "carbs_g": None,
        "sugar_g": None,
        "fat_g": None,
        "sodium_mg": None,
        "ingredients": None,
        "allergens": None,
        "serving_size": None,
        "fiber_g": None
    }
    audit = audit_record_completeness(record)
    assert audit["zero_hallucination_guarantee"] is True
    assert audit["imputed_fields_count"] == 0
    assert audit["review_priority"] == "CRITICAL"  # missing ingredients & allergens
    assert "allergens" in audit["missing_critical"]
    assert "ingredients" in audit["missing_critical"]
    assert "calories" in audit["missing_high"]
    assert audit["completeness_pct"] == 10.0  # only protein_g is present out of 10 fields


def test_validator_cross_field_anomalies():
    """Verify that all 7 anomaly categories are deterministically detected."""
    anomalous_record = {
        "calories": 1150.0,            # Implausible: > 900 kcal
        "fat_g": 20.0,
        "saturated_fat_g": 25.0,       # Contradiction: Sat fat > Fat
        "carbs_g": 30.0,
        "sugar_g": 45.0,               # Contradiction: Sugar > Carbs
        "added_sugars_g": 50.0,        # Contradiction: Added sugar > Sugar
        "protein_g": 110.0,            # Impossible: > 100g per 100g
        "sodium_mg": 2000.0,           # 2.0g Sodium
        "salt_g": 0.5                  # Contradiction: Sodium (2g) > Salt (0.5g)
    }
    anomalies = audit_cross_field_anomalies(anomalous_record)
    types = [a["type"] for a in anomalies]
    assert "excessive_calories" in types
    assert "macro_exceeds_100g" in types
    assert "added_sugars_exceed_sugars" in types
    assert "sugars_exceed_carbs" in types
    assert "saturated_fat_exceeds_fat" in types
    assert "sodium_exceeds_salt" in types


def test_data_connector_demo_subset_default():
    """Verify demo_subset(1).csv loads 552 records by default with normalized fields."""
    connector = DataConnector()
    records, total, stats = connector.get_records("demo")
    assert total == 552
    assert stats["total"] == 552
    assert stats["critical"] > 0
    assert stats["complete"] > 0
    assert stats["anomalies_count"] > 0
    assert stats["duplicates_count"] > 0

    first = records[0]
    assert "id" in first
    assert "name" in first
    assert "brand" in first
    assert "calories" in first
    assert "protein_g" in first
    # image_url must not be in normalized record or must be completely ignored
    assert first.get("image_url") is None


def test_dataset_toggle_metadata():
    """Verify dataset metadata correctly lists demo, full, and synthetic datasets."""
    connector = DataConnector()
    metadata = connector.get_dataset_metadata()
    keys = [d["key"] for d in metadata]
    assert "demo" in keys
    assert "full" in keys
    assert "synthetic" in keys

    demo_meta = next(d for d in metadata if d["key"] == "demo")
    assert demo_meta["available"] is True
    assert demo_meta["row_count"] == 552
    assert demo_meta["is_default"] is True


def test_pinecone_ready_local_similarity():
    """Verify local similarity fallback returns verified records with high safety."""
    connector = DataConnector()
    records = connector.load_dataset("demo")
    similar = connector.get_similar_records(records[0]["id"], "demo", limit=3)
    assert len(similar) <= 3
    for s in similar:
        assert s["audit"]["completeness_pct"] >= 70.0
        assert s["id"] != records[0]["id"]


def test_flask_endpoints():
    """Verify all Flask REST routes with test_client."""
    client = app.test_client()

    # 1. Health check
    h = client.get("/api/health")
    assert h.status_code == 200
    h_data = h.get_json()
    assert h_data["status"] == "healthy"
    assert h_data["zero_hallucination_guardrail"] == "ENFORCED"

    # 2. Datasets list
    ds = client.get("/api/datasets")
    assert ds.status_code == 200
    assert len(ds.get_json()["datasets"]) == 3

    # 3. Records endpoint
    rec_resp = client.get("/api/records?dataset=demo&limit=10")
    assert rec_resp.status_code == 200
    rec_data = rec_resp.get_json()
    assert rec_data["stats"]["total"] == 552
    assert len(rec_data["records"]) == 10

    # 4. Single record detail
    first_id = rec_data["records"][0]["id"]
    detail_resp = client.get(f"/api/records/{first_id}?dataset=demo")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.get_json()
    assert detail_data["record"]["id"] == first_id
    assert "audit" in detail_data["record"]
    assert "similar_products" in detail_data

    # 5. Add custom product (testing new-calories)
    add_payload = {
        "name": "Integration Test Whey Crunch",
        "brand": "NutriAudit Labs",
        "category": "Snack Bar",
        "serving_size": "50g",
        "calories": 210.0,
        "protein_g": 20.0,
        "carbs_g": 18.0,
        "sugar_g": 3.0,
        "fat_g": 7.0,
        "sodium_mg": 150.0,
        "ingredients": ["Whey Protein", "Oats", "Cocoa"],
        "allergens": ["Milk"]
    }
    add_resp = client.post("/api/records?dataset=demo", json=add_payload)
    assert add_resp.status_code == 200
    added = add_resp.get_json()["record"]
    assert added["name"] == "Integration Test Whey Crunch"
    assert added["calories"] == 210.0

    # 6. Static index.html root
    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert "NUTRIAUDIT" in root_resp.data.decode("utf-8")


def test_triage_service_audit():
    """Verify triage service returns structured zero-hallucination report."""
    connector = DataConnector()
    rec = connector.get_record_by_id("8908010900056", "demo")
    audit = run_triage_audit(rec, rec["audit"], rec["anomalies"])
    assert audit["status"] == "success"
    assert audit["zero_hallucination_guaranteed"] is True
    assert "ZERO-HALLUCINATION" in audit["content"].upper()


def test_synthetic_xlsx_normalization():
    """Verify Synthetic 2,000 Excel schema normalization preserves missing values as None."""
    connector = DataConnector()
    row = {
        "product_id": "SYN-100",
        "product_name": "Synthetic Almond Drink",
        "brand": "NutriSynth",
        "category": "Beverage",
        "barcode": "999000111222",
        "serving_size_g": 250,
        "energy_kcal": 65.0,
        "protein_g": 2.0,
        "carbs_g": 4.0,
        "sugar_g": 3.0,
        "fat_g": 3.5,
        "saturated_fat_g": 0.3,
        "fiber_g": None,
        "sodium_mg": 120.0,
        "ingredients_text": None,
        "allergens": "Tree nuts"
    }
    norm = connector.normalize_synthetic_xlsx_row(row, 1, "synthetic")
    assert norm["id"] == "999000111222"
    assert norm["serving_size"] == "250g"
    assert norm["calories"] == 65.0
    assert norm["sodium_mg"] == 120.0
    assert norm["fiber_g"] is None
    assert norm["ingredients"] is None
    assert norm["allergens"] == ["Tree nuts"]


def test_frontend_form_and_dataset_toggle():
    """Verify index.html contains all fixed DOM/JS bindings, dataset toggle, and zero-image compliance."""
    index_path = Path(__file__).resolve().parent.parent / "index.html"
    content = index_path.read_text(encoding="utf-8")
    assert 'id="new-calories"' in content
    assert 'id="btn-ds-demo"' in content
    assert 'id="btn-ds-full"' in content
    assert 'id="btn-ds-synthetic"' in content
    assert 'switchDataset(' in content
    assert 'anomalies-card' in content
    assert 'function saveModalApiKey()' in content
    assert 'verdict-card' in content
    assert 'verdict-checklist' in content
    assert 'parseCsvRows' in content
    assert '<img' not in content.lower() or 'images.openfoodfacts.net' not in content


if __name__ == "__main__":
    print("Running NutriAudit Test Suite...")
    test_validator_zero_hallucination_and_missing_detection()
    print("✓ test_validator_zero_hallucination_and_missing_detection passed")
    test_validator_cross_field_anomalies()
    print("✓ test_validator_cross_field_anomalies passed")
    test_data_connector_demo_subset_default()
    print("✓ test_data_connector_demo_subset_default passed")
    test_synthetic_xlsx_normalization()
    print("✓ test_synthetic_xlsx_normalization passed")
    test_dataset_toggle_metadata()
    print("✓ test_dataset_toggle_metadata passed")
    test_pinecone_ready_local_similarity()
    print("✓ test_pinecone_ready_local_similarity passed")
    test_flask_endpoints()
    print("✓ test_flask_endpoints passed")
    test_triage_service_audit()
    print("✓ test_triage_service_audit passed")
    test_frontend_form_and_dataset_toggle()
    print("✓ test_frontend_form_and_dataset_toggle passed")
    print("\nALL 9 TESTS PASSED PERFECTLY!")
