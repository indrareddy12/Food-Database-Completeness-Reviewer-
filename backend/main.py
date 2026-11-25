"""
NutriAudit Backend Server (Flask)
PS 134: Food Database Completeness Reviewer
Serves REST API, dataset toggle, deterministic validator, and Groq/Gemini GenAI triage.
"""

import os
import sys
import logging
from pathlib import Path

# Configure baseline logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nutriaudit.api")

# Ensure backend directory is in python path
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

from data_connector import DataConnector, DATASET_CONFIGS, UPLOAD_DIR
from triage_service import (
    run_triage_audit,
    get_active_groq_key,
    get_active_gemini_key
)

frontend_dir = current_dir.parent
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".xlsx"}

app = Flask(__name__, static_folder=str(frontend_dir))
CORS(app, resources={r"/*": {"origins": "*"}})

# Initialize connector
connector = DataConnector()


# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint showing backend status, Groq key presence, and active dataset."""
    groq_key = get_active_groq_key()
    gemini_key = get_active_gemini_key()
    pinecone_key = os.getenv("PINECONE_API_KEY")
    pinecone_configured = bool(pinecone_key and pinecone_key != "your_pinecone_api_key_here")

    return jsonify({
        "status": "healthy",
        "service": "NutriAudit Food Database Completeness Reviewer",
        "active_dataset": connector.active_dataset_key,
        "groq_configured": bool(groq_key),
        "groq_key_prefix": (groq_key[:8] + "...") if groq_key else None,
        "gemini_configured": bool(gemini_key),
        "pinecone_configured": pinecone_configured,
        "zero_hallucination_guardrail": "ENFORCED"
    })


@app.route("/api/datasets", methods=["GET"])
def list_datasets():
    """List all supported datasets with availability, path, and active state."""
    return jsonify({
        "active_dataset": connector.active_dataset_key,
        "datasets": connector.get_dataset_metadata()
    })


@app.route("/api/datasets/active", methods=["POST"])
def switch_active_dataset():
    """Switch active dataset ('demo', 'full', 'synthetic')."""
    data = request.get_json(silent=True) or {}
    key = str(data.get("dataset_key", "")).lower().strip()
    if key not in DATASET_CONFIGS:
        return jsonify({"error": f"Invalid dataset key '{key}'. Supported: {list(DATASET_CONFIGS.keys())}"}), 400

    try:
        connector.load_dataset(key)
        connector.active_dataset_key = key
    except FileNotFoundError as e:
        logger.warning("Dataset '%s' not found: %s", key, e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("Failed to switch to dataset '%s': %s", key, e)
        return jsonify({"error": f"Failed to load dataset '{key}': {str(e)}"}), 500

    return jsonify({
        "status": "success",
        "active_dataset": connector.active_dataset_key,
        "datasets": connector.get_dataset_metadata()
    })


@app.route("/api/datasets/upload", methods=["POST"])
def upload_dataset_file():
    """
    Upload preprocessed_full(1).csv or food_completeness_dataset_2000.xlsx safely.
    Sanitizes filename with werkzeug.utils.secure_filename(), validates extension,
    and writes exclusively into an isolated uploads/ directory.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    raw_filename = (file.filename or "").strip()
    if not raw_filename:
        return jsonify({"error": "Empty filename"}), 400

    # Reject explicit traversal paths or suspicious filenames
    if ".." in raw_filename or "/" in raw_filename or "\\" in raw_filename:
        safe_candidate = Path(raw_filename).name
        if safe_candidate != raw_filename:
            return jsonify({"error": "Invalid filename: path traversal characters are forbidden."}), 400

    safe_filename = secure_filename(raw_filename)
    if not safe_filename:
        return jsonify({"error": "Invalid filename after sanitization."}), 400

    ext = Path(safe_filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({
            "error": f"Unsupported file extension '{ext}'. Allowed extensions: {sorted(ALLOWED_UPLOAD_EXTENSIONS)}"
        }), 400

    resolved_upload_dir = UPLOAD_DIR.resolve()
    resolved_upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = (resolved_upload_dir / safe_filename).resolve()

    if not target_path.is_relative_to(resolved_upload_dir):
        return jsonify({"error": "Invalid upload path: escapes sandboxed upload directory."}), 400

    file.save(str(target_path))
    logger.info("Saved uploaded dataset '%s' to %s", safe_filename, target_path)

    # Invalidate cache
    connector._cache.clear()
    connector._duplicates_cache.clear()

    matched_key = None
    # Match against canonical or sanitized dataset names
    for key, conf in DATASET_CONFIGS.items():
        if safe_filename in conf["filenames"] or safe_filename in {secure_filename(fn) for fn in conf["filenames"]}:
            matched_key = key
            break

    if matched_key:
        connector.active_dataset_key = matched_key

    return jsonify({
        "status": "success",
        "filename": safe_filename,
        "matched_dataset": matched_key,
        "message": f"Successfully uploaded '{safe_filename}' into isolated uploads directory.",
        "datasets": connector.get_dataset_metadata()
    })


@app.route("/api/records", methods=["GET"])
def get_records():
    """Fetch paginated, filtered food records with full dataset summary statistics."""
    dataset = request.args.get("dataset") or connector.active_dataset_key
    search = request.args.get("search", "")
    priority = request.args.get("priority", "ALL")
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", default=0, type=int)

    try:
        records_page, total_filtered, stats = connector.get_records(
            dataset_key=dataset,
            search=search,
            priority=priority,
            limit=limit,
            offset=offset
        )
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("Error loading records for dataset '%s': %s", dataset, e)
        return jsonify({"error": f"Error loading records: {str(e)}"}), 500

    return jsonify({
        "dataset_key": dataset,
        "total_filtered": total_filtered,
        "limit": limit,
        "offset": offset,
        "stats": stats,
        "records": records_page
    })


@app.route("/api/records/<record_id>", methods=["GET"])
def get_record(record_id: str):
    """Fetch single product record with full audit, anomalies, duplicates, and Pinecone-ready similar items."""
    dataset = request.args.get("dataset") or connector.active_dataset_key
    try:
        rec = connector.get_record_by_id(record_id, dataset)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("Error retrieving record '%s': %s", record_id, e)
        return jsonify({"error": f"Failed to retrieve record: {str(e)}"}), 500

    if not rec:
        return jsonify({"error": f"Record '{record_id}' not found in dataset '{dataset}'"}), 404

    similar = connector.get_similar_records(record_id, dataset, limit=3)

    return jsonify({
        "dataset_key": dataset,
        "record": rec,
        "similar_products": similar
    })


@app.route("/api/audit/<record_id>", methods=["POST"])
def audit_product_triage(record_id: str):
    """
    Run GenAI Deep Audit using Groq or Gemini under the Zero-Hallucination Contract.
    Uses backend GROQ_API_KEY from .env by default.
    """
    dataset = request.args.get("dataset") or connector.active_dataset_key
    try:
        rec = connector.get_record_by_id(record_id, dataset)
    except Exception as e:
        logger.exception("Error fetching record '%s' for triage: %s", record_id, e)
        return jsonify({"error": str(e)}), 500

    if not rec:
        return jsonify({"error": f"Record '{record_id}' not found in dataset '{dataset}'"}), 404

    data = request.get_json(silent=True) or {}
    client_groq = data.get("groq_api_key")
    client_gemini = data.get("gemini_api_key")

    audit_result = run_triage_audit(
        record=rec,
        audit=rec.get("audit", {}),
        anomalies=rec.get("anomalies", []),
        client_groq_key=client_groq,
        client_gemini_key=client_gemini
    )

    return jsonify(audit_result)


@app.route("/api/records", methods=["POST"])
def add_product_record():
    """Add a custom product to the active dataset session and audit it deterministically."""
    dataset = request.args.get("dataset") or connector.active_dataset_key
    data = request.get_json(silent=True) or {}
    new_record = connector.add_custom_record(data, dataset)
    return jsonify({
        "status": "success",
        "message": f"Added and audited '{new_record.get('name') or new_record.get('id')}' successfully.",
        "record": new_record
    })


# -----------------------------------------------------------------------------
# Static File Hosting (Serves index.html at root)
# -----------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def serve_index():
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return send_file(index_file)
    return jsonify({"message": "NutriAudit API is running. index.html not found."})


@app.route("/<path:path>", methods=["GET"])
def serve_static(path):
    file_path = frontend_dir / path
    if file_path.exists():
        return send_from_directory(str(frontend_dir), path)
    return send_file(str(frontend_dir / "index.html"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info("Starting NutriAudit Backend Server on http://localhost:%s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
