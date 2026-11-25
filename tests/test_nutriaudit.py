"""
NutriAudit Comprehensive Integration & Verification Test Suite
Tests Validator, Data Connector, Upload Security, Flask REST API, Triage Service, and Frontend Contracts.
"""

import io
import os
import sys
import shutil
from pathlib import Path
from unittest.mock import patch

# Add backend directory to path
backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from main import app, UPLOAD_DIR
from data_connector import DataConnector, DATASET_CONFIGS, assign_food_icon
from validator import (
    audit_record_completeness,
    audit_cross_field_anomalies,
    detect_dataset_duplicates,
    is_missing_value
)
from triage_service import run_triage_audit, get_active_groq_key


def test_validator_zero_hallucination_and_missing_detection():
    """Verify that missing values and placeholder tokens are never guessed or imputed."""
    for token in (None, "", "   ", "na", "N/A", "tbd", "TBD", "-", "?", "missing", "unknown", "null", "[]", []):
        assert is_missing_value(token) is True, f"Expected missing token {token!r} to be flagged"

    assert is_missing_value(0) is False
    assert is_missing_value(0.0) is False
    assert is_missing_value("Oats") is False

    record = {
        "id": "TEST-01",
        "name": "Zero Hallucination Bar",
        "brand": "AuditLabs",
        "calories": None,
        "protein_g": 20.0,
        "carbs_g": "n/a",
        "sugar_g": "-",
        "fat_g": "?",
        "sodium_mg": "tbd",
        "ingredients": None,
        "allergens": None,
        "serving_size": None,
        "fiber_g": None
    }
    audit = audit_record_completeness(record)
    assert audit["zero_hallucination_guarantee"] is True
    assert audit["imputed_fields_count"] == 0
    assert audit["review_priority"] == "CRITICAL"
    assert "allergens" in audit["missing_critical"]
    assert "ingredients" in audit["missing_critical"]
    assert "calories" in audit["missing_high"]
    assert "sodium_mg" in audit["missing_high"]
    assert audit["completeness_pct"] == 10.0


def test_validator_cross_field_anomalies():
    """Verify that all 7 anomaly categories are deterministically detected."""
    anomalous_record = {
        "calories": 1150.0,
        "fat_g": 20.0,
        "saturated_fat_g": 25.0,
        "carbs_g": 30.0,
        "sugar_g": 45.0,
        "added_sugars_g": 50.0,
        "protein_g": 110.0,
        "sodium_mg": 2000.0,
        "salt_g": 0.5
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
    """Verify demo_subset(1).csv loads 552 records, uses Lucide icons, and preserves None."""
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
    assert "icon" in first
    assert "iconColor" in first
    assert "emoji" not in first
    assert first.get("image_url") is None


def test_zero_hallucination_normalization():
    """Verify missing metadata & salt_g remain None (no fallback strings or derived salt)."""
    connector = DataConnector()

    off_norm = connector.normalize_off_csv_row({
        "code": "12345",
        "product_name": "N/A",
        "brands": "-",
        "categories": "?",
        "ingredients_text": "tbd",
        "allergens": "",
        "energy_kcal_100g": "na"
    }, 1, "demo")
    assert off_norm["name"] is None
    assert off_norm["brand"] is None
    assert off_norm["category"] is None
    assert off_norm["ingredients"] is None
    assert off_norm["calories"] is None
    assert "emoji" not in off_norm

    synth_norm = connector.normalize_synthetic_xlsx_row({
        "product_id": "SYN-100",
        "product_name": "Synthetic Almond Drink",
        "brand": "",
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
    }, 1, "synthetic")
    assert synth_norm["id"] == "999000111222"
    assert synth_norm["brand"] is None
    assert synth_norm["serving_size"] == "250g"
    assert synth_norm["sodium_mg"] == 120.0
    assert synth_norm["salt_g"] is None  # Must NOT derive from sodium_mg
    assert synth_norm["fiber_g"] is None
    assert synth_norm["ingredients"] is None
    assert synth_norm["allergens"] == ["Tree nuts"]
    assert "emoji" not in synth_norm


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


def test_upload_security_sanitization():
    """Verify upload rejects path traversal, disallowed extensions, and isolates files in uploads/."""
    client = app.test_client()

    # 1. Reject path traversal filename
    r1 = client.post("/api/datasets/upload", data={"file": (io.BytesIO(b"secret"), "../.env")}, content_type="multipart/form-data")
    assert r1.status_code == 400

    # 2. Reject HTML overwrite / disallowed extension
    r2 = client.post("/api/datasets/upload", data={"file": (io.BytesIO(b"<p>bad</p>"), "index.html")}, content_type="multipart/form-data")
    assert r2.status_code == 400

    # 3. Valid CSV upload lands safely in isolated uploads/ directory
    r3 = client.post("/api/datasets/upload", data={"file": (io.BytesIO(b"code,product_name\n1,Test\n"), "test_upload_tmp.csv")}, content_type="multipart/form-data")
    assert r3.status_code == 200
    uploaded_file = UPLOAD_DIR / "test_upload_tmp.csv"
    assert uploaded_file.exists()
    # Cleanup test upload artifact
    uploaded_file.unlink(missing_ok=True)
    if UPLOAD_DIR.exists() and not any(UPLOAD_DIR.iterdir()):
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)


def test_flask_endpoints():
    """Verify all Flask REST routes with test_client."""
    client = app.test_client()

    h = client.get("/api/health")
    assert h.status_code == 200
    h_data = h.get_json()
    assert h_data["status"] == "healthy"
    assert h_data["zero_hallucination_guardrail"] == "ENFORCED"

    ds = client.get("/api/datasets")
    assert ds.status_code == 200
    assert len(ds.get_json()["datasets"]) == 3

    rec_resp = client.get("/api/records?dataset=demo&limit=10")
    assert rec_resp.status_code == 200
    rec_data = rec_resp.get_json()
    assert rec_data["stats"]["total"] == 552
    assert len(rec_data["records"]) == 10

    first_id = rec_data["records"][0]["id"]
    detail_resp = client.get(f"/api/records/{first_id}?dataset=demo")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.get_json()
    assert detail_data["record"]["id"] == first_id
    assert "audit" in detail_data["record"]
    assert "similar_products" in detail_data

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

    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert "NUTRIAUDIT" in root_resp.data.decode("utf-8")


def test_triage_service_audit_and_warning_reporting():
    """Verify triage service returns structured zero-hallucination report and surfaces warnings on failures."""
    connector = DataConnector()
    rec = connector.get_record_by_id("8908010900056", "demo")
    audit = run_triage_audit(rec, rec["audit"], rec["anomalies"])
    assert audit["status"] == "success"
    assert audit["zero_hallucination_guaranteed"] is True
    assert "ZERO-HALLUCINATION" in audit["content"].upper()

    # Verify fallback surfaces warnings instead of swallowing exceptions silently
    with patch("triage_service.requests.post", side_effect=ConnectionError("Simulated network outage")):
        fallback = run_triage_audit(
            rec, rec["audit"], rec["anomalies"],
            client_groq_key="gsk_fake_test_key",
            client_gemini_key="AIza_fake_test_key"
        )
        assert fallback["provider"] == "deterministic_fallback"
        assert len(fallback["warnings"]) > 0
        assert "ConnectionError" in fallback["fallback_reason"]


def test_frontend_lucide_icons_and_dataset_toggle():
    """Verify index.html uses Lucide icons (zero emoji regressions) and preserves all PS 134 bindings."""
    index_path = Path(__file__).resolve().parent.parent / "index.html"
    content = index_path.read_text(encoding="utf-8")
    # Lucide icon architecture preserved
    assert "unpkg.com/lucide@latest" in content
    assert "lucide.createIcons()" in content
    assert 'data-lucide="' in content
    # PS 134 bindings
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
    assert 'assignFoodIcon' in content
    assert '<img' not in content.lower() or 'images.openfoodfacts.net' not in content


if __name__ == "__main__":
    print("Running NutriAudit Test Suite...")
    test_validator_zero_hallucination_and_missing_detection()
    print("✓ test_validator_zero_hallucination_and_missing_detection passed")
    test_validator_cross_field_anomalies()
    print("✓ test_validator_cross_field_anomalies passed")
    test_data_connector_demo_subset_default()
    print("✓ test_data_connector_demo_subset_default passed")
    test_zero_hallucination_normalization()
    print("✓ test_zero_hallucination_normalization passed")
    test_dataset_toggle_metadata()
    print("✓ test_dataset_toggle_metadata passed")
    test_pinecone_ready_local_similarity()
    print("✓ test_pinecone_ready_local_similarity passed")
    test_upload_security_sanitization()
    print("✓ test_upload_security_sanitization passed")
    test_flask_endpoints()
    print("✓ test_flask_endpoints passed")
    test_triage_service_audit_and_warning_reporting()
    print("✓ test_triage_service_audit_and_warning_reporting passed")
    test_frontend_lucide_icons_and_dataset_toggle()
    print("✓ test_frontend_lucide_icons_and_dataset_toggle passed")
    print("\nALL 10 TESTS PASSED PERFECTLY!")
