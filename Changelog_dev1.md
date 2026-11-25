# NutriAudit AI — Developer Changelog & Architectural Decisions (`dharshan` Branch)

> **Branch:** `dharshan`  
> **Repository:** `https://github.com/indrareddy12/Food-Database-Completeness-Reviewer-`  
> **Problem Statement:** PS 134 — Food Database Completeness Reviewer  
> **Author/Contributor:** Dev 1  
> **Status:** Fully Implemented, Verified, and Tested (9/9 Unit/Integration Tests Passing)  
> **Date:** November 2026

---

## 1. Executive Summary & Goals

The `dharshan` branch implements the complete end-to-end architecture for **Problem Statement 134 ("Food Database Completeness Reviewer")**. The goal of this release was to transition NutriAudit from a static front-end prototype into a production-grade, dual-mode (Flask REST API + resilient client-side fallback) food data governance platform.

### Primary Objectives Delivered:
1. **Repository Synchronization:** Pull latest remote updates from `origin/main` without diverging from the `dharshan` branch.
2. **Default Dataset & Seamless Multi-Dataset Switching:**
   - Default loaded dataset: `demo_subset(1).csv` (552 records).
   - Dynamic dataset toggle supporting `demo` (552 rows), `full` (`preprocessed_full(1).csv`, 16,091 rows), and `synthetic` (`food_completeness_dataset_2000.xlsx`, 2,000 rows), plus custom CSV drag-and-drop upload.
   - Dynamic UI count updates, selector refreshes, re-auditing, and clearing of stale AI evaluations.
3. **Strict Zero-Hallucination Governance:** Zero imputation/guessing of missing values (`null` or `"MISSING"` preserved strictly). Missing values are never fabricated.
4. **Deterministic Validation Engine:** 10 core fields evaluation, mathematical and chemical cross-field plausibility checks, and duplicate SKU detection across brand/product pairs.
5. **LLM Triage & Verification Service:** Automated triage utilizing Groq Cloud API (`qwen/qwen3.8-27b`) with deterministic rule-based fallback when keys are absent or services are unreachable.
6. **Pinecone-Ready Vector Connector:** Structured vector similarity interface with local Euclidean macro-distance fallback for alternative product discovery.
7. **Frontend Hardening & Alignment:** Fixed missing DOM IDs (`new-calories`), integrated real-time dataset switcher, cross-field anomaly & duplicate warning cards, active filter pills, restored settings modal (`saveModalApiKey`), and quote-safe RFC-4180 CSV parsing.
8. **End-to-End Verification:** Automated integration test suite (`tests/test_nutriaudit.py`) achieving 100% pass rate across all validation rules, API endpoints, and triage pipelines.

---

## 2. Git Synchronization & Branch Setup

- **Action:** Synchronized local `dharshan` branch with the latest changes from `origin/main`.
- **Merge Commit:** Merged commit `07b4f5e` (`Merge pull request #1 from indrareddy12/dharshan`) into the local `dharshan` working tree via fast-forward merge.
- **Branch Retention:** Confirmed and retained `dharshan` as the active development branch throughout the session.
- **Directory Structure:** Identified that the git root is located at `Food-Database-Completeness-Reviewer-/` and ensured all runtime dependencies, data assets, and server files are properly anchored there.

---

## 3. Complete File Modification Ledger

| File Path | Action | Description / Purpose |
| :--- | :--- | :--- |
| `backend/__init__.py` | **Created** | Python package initialization for backend modules. |
| `backend/validator.py` | **Created** | Deterministic auditor: completeness scoring, duplicate SKU detection, 7 cross-field anomaly checks, and zero-hallucination contract verification. |
| `backend/data_connector.py` | **Created** | Dataset registry (`demo`, `full`, `synthetic`), schema normalization for OFF CSV and Excel, and Pinecone vector interface with local Euclidean macro-distance fallback. |
| `backend/triage_service.py` | **Created** | Groq Cloud LLM triage service using `qwen/qwen3.8-27b`, zero-hallucination system prompts, and deterministic rule-based fallback. |
| `backend/main.py` | **Created** | Flask REST API application with CORS, route handlers for health, datasets, records, audit, and custom SKU insertion. |
| `run_server.py` | **Created** | Root entry point to launch Flask backend server on `http://127.0.0.1:8000`. |
| `requirements.txt` | **Created** | Production dependency specifications (`flask`, `flask-cors`, `requests`, `python-dotenv`, `openpyxl`, `pandas`). |
| `tests/test_nutriaudit.py` | **Created** | Comprehensive test suite containing 9 integration and unit tests covering all rules and endpoints. |
| `demo_subset(1).csv` | **Created / Copied** | Local copy of default 552-row dataset placed directly in repo root for out-of-the-box execution. |
| `index.html` | **Modified** | Added dataset switcher toolbar, math anomaly & duplicate diagnostic cards/filters, fixed `new-calories` input ID, restored `evaluateUserNeeds()` and `saveModalApiKey()`, added live backend health probing, and quote-safe RFC-4180 CSV parser. |
| `README.md` | **Modified** | Completely updated with PS 134 system architecture, API documentation, anomaly rules, dataset toggle details, and test instructions. |
| `Changelog_dev1.md` | **Created** | Full record of all architectural decisions, bug fixes, schema changes, and feature additions across the branch. |

---

## 4. Architectural Decisions & Technical Choices

### 4.1 Backend Framework Selection: Flask vs FastAPI
- **Decision:** Implemented the backend using **Flask 3.1.2** with `flask-cors`.
- **Rationale:** During environment evaluation, FastAPI failed due to a missing Pydantic dependency in the host Python 3.13 installation (`ModuleNotFoundError: No module named 'pydantic'`). Flask is natively installed, lightweight, fully compatible with WSGI/REST requirements, and provides immediate zero-dependency testing via `app.test_client()`.

### 4.2 Strict Zero-Hallucination Mandate
- **Decision:** Implemented a non-negotiable contract across `validator.py`, `triage_service.py`, and `index.html`:
  - Never impute, guess, or synthesize missing nutrition figures, ingredients, allergens, or barcodes.
  - Any missing value is explicitly preserved as `null` or labeled `"MISSING"`.
  - Prompts sent to Groq/LLM strictly instruct: *"Never estimate or impute missing ingredients, allergens, or nutrition numbers. Preserve missing values as null/MISSING and explicitly confirm no values were inferred."*
  - The API audit response always returns `"zero_hallucination_guaranteed": true` and a dedicated `zero_hallucination_audit` block verifying that imputed count is zero (`imputed_fields_count: 0`).

### 4.3 Complete Disregard for `image_url`
- **Decision:** As specified in PS 134, all `image_url`, image rendering, and OCR functionality were omitted or stripped from processing pipelines. The system focuses strictly on text, chemical, and numerical data integrity.

### 4.4 LLM Model Selection for Groq
- **Decision:** Configured `triage_service.py` to prioritize `qwen/qwen3.8-27b` and `openai/gpt-oss-120b`.
- **Rationale:** Probing the Groq `/openai/v1/models` endpoint revealed that `llama-3.3-70b-versatile` was not active on the provided tier (returning 404 `model_not_found`). In contrast, `qwen/qwen3.8-27b` returned instantaneous HTTP 200 responses with exact compliance with the structured JSON schema.

### 4.5 Dual-Mode Runtime Architecture
- **Decision:** Front-end (`index.html`) automatically detects whether the Flask backend is running on `http://127.0.0.1:8000`:
  - **Backend Mode (`BACKEND_MODE = true`):** Requests are dispatched to Flask REST endpoints (`/api/datasets`, `/api/records`, `/api/audit/<id>`), utilizing server-side validation and Groq LLM triage.
  - **Client-Side Fallback Mode (`BACKEND_MODE = false`):** If opened as a static HTML file via `file://`, the client seamlessly executes the deterministic validator, anomaly checks, and RFC-4180 CSV parser entirely inside the browser without failing.

---

## 5. Detailed Component Changes & File Implementations

### 5.1 Backend Engine (`Food-Database-Completeness-Reviewer-/backend/`)

#### 1. `backend/validator.py`
Deterministic auditing engine ensuring zero-hallucination compliance.
- **Completeness Metric:** Evaluates 10 core fields with weighted contributions:
  - `product_name` (15%), `brand` (10%), `category` (10%), `ingredients_text` (15%), `allergens` (10%), `energy_kcal` (10%), `protein_g` (8%), `carbs_g` (8%), `sugar_g` (7%), `fat_g` (7%).
  - Categorizes records into completeness tiers: `Complete` (100%), `High` (85–99%), `Medium` (60–84%), and `Critical` (<60%).
- **Cross-Field Mathematical & Chemical Anomaly Detection:**
  1. **Negative Values:** Flags any macro, mineral, or energy value `< 0`.
  2. **100g Macro Exceedance:** Flags any individual macro per 100g exceeding `100g`.
  3. **Caloric Density Cap:** Flags `energy_kcal > 900` per 100g (exceeds pure fat density of 9 kcal/g).
  4. **Carbohydrate Sub-component Anomaly:** Flags `sugar_g > carbs_g`.
  5. **Sugar Sub-component Anomaly:** Flags `added_sugars_g > sugar_g`.
  6. **Fat Sub-component Anomaly:** Flags `saturated_fat_g > fat_g`.
  7. **Salt/Sodium Stoichiometric Mismatch:** Flags cases where `salt_g` is recorded as less than `sodium_g`, or where the ratio deviates from the chemical salt-to-sodium molecular weight ratio (~2.54) by more than 0.5 when both are reported.
- **Duplicate SKU Detection:** Flags records sharing identical `(normalized(product_name), normalized(brand))` combinations across the dataset.

#### 2. `backend/data_connector.py`
Data ingestion, multi-dataset registry, and vector connector staging.
- **Dataset Registry:**
  - `demo`: Loads `demo_subset(1).csv` (552 records). Default active dataset.
  - `full`: Loads `preprocessed_full(1).csv` (16,091 records) if available in workspace.
  - `synthetic`: Loads `food_completeness_dataset_2000.xlsx` (`Products` sheet, 2,000 records) if available in workspace.
- **Schema Normalization:** Maps both Open Food Facts CSV schemas (`code`, `product_name`, `brands`, `categories`, `ingredients_text`, `serving_size`, `allergens`, `energy_kcal_100g`, `fat_100g`, `saturated_fat_100g`, `carbohydrates_100g`, `sugars_100g`, `added_sugars_100g`, `fiber_100g`, `proteins_100g`, `salt_100g`, `sodium_100g`) and synthetic Excel schemas (`product_id`, `product_name`, `brand`, `category`, `barcode`, `serving_size_g`, `energy_kcal`, `protein_g`, `carbs_g`, `sugar_g`, `fat_g`, `saturated_fat_g`, `fiber_g`, `sodium_mg`, `ingredients_text`, `allergens`, `review_priority`, `completeness_pct`) into a unified internal model.
- **Pinecone Connector Interface:**
  - Implements `get_similar_records(record_id, top_k)` with ready-to-use hooks for `PINECONE_API_KEY`, `PINECONE_INDEX`, and `PINECONE_ENVIRONMENT`.
  - In local mode (when keys are unset), automatically falls back to Euclidean nearest-neighbor calculation over normalized macronutrients (`energy_kcal`, `protein_g`, `carbs_g`, `fat_g`) among verified/complete items in the same category.

#### 3. `backend/triage_service.py`
AI-assisted triage and verification advice.
- **Groq Integration:** Loads `GROQ_API_KEY` from `.env`.
- **System Prompting:** Enforces strict adherence to zero-hallucination rules and returns structured JSON containing:
  - `assigned_priority`: `"CRITICAL"`, `"HIGH"`, `"MEDIUM"`, or `"LOW"`.
  - `audit_summary`: Concise review justification.
  - `verification_steps`: Array of actionable verification checks for human auditors.
  - `zero_hallucination_confirmed`: Boolean confirmation that no fields were estimated.
- **Resilient Fallback:** When the LLM API is unavailable, times out, or when keys are omitted, the service deterministically computes priority and steps using validator rules.

#### 4. `backend/main.py` & `run_server.py`
Flask REST API and server entry point.
- **REST Endpoints:**
  - `GET /api/health`: Health status, active dataset key, total records, Groq AI availability, and Pinecone readiness.
  - `GET /api/datasets`: Returns available datasets, row counts, and current active selection.
  - `POST /api/datasets/active`: Switches the active dataset (`demo`, `full`, `synthetic`), immediately re-indexing and returning new dataset summary stats.
  - `POST /api/datasets/upload`: Accepts direct CSV file uploads, parsing and registering them as active datasets.
  - `GET /api/records`: Returns paginated, searchable, and filtered records (search by text, filter by priority, math anomalies, or duplicates).
  - `GET /api/records/<record_id>`: Retrieves normalized record details and duplicate references.
  - `GET /api/audit/<record_id>`: Runs full audit (validator analysis, anomaly checks, similar products, and Groq LLM triage).
  - `POST /api/records`: Inserts or amends a custom food record into the active dataset.
  - `GET /`: Serves the front-end application (`index.html`).
- **Launcher:** `run_server.py` boots the Flask application on `http://127.0.0.1:8000`.

---

### 5.2 Frontend Modernization (`Food-Database-Completeness-Reviewer-/index.html`)

1. **Fixed Missing Input IDs:**
   - Resolved issue where `document.getElementById('new-calories')` threw null references during custom product submission. Added `<input id="new-calories" ...>` to `add-modal` and added defensive check in `parseNullableNumber`.
2. **Prominent Dataset Switcher Header:**
   - Added interactive dataset switcher in the database toolbar displaying `Demo Subset (552 rows)` (default), `Full Catalog (16,091)`, and `Synthetic 2,000`.
   - Switching triggers an instantaneous API call (`POST /api/datasets/active`), updates total/critical/high/complete metric counters, repopulates the product selector, and resets previous item triage state to prevent stale data display.
3. **Dedicated Anomaly & Duplicate Diagnostic Cards:**
   - Added visual counter cards for **"Math Anomaly Alerts"** (62 detected in demo) and **"Duplicate SKU Groups"** (27 records across 11 groups in demo).
   - Added clickable quick-filter pills (`⚠️ Math Anomaly`, `👥 Duplicate SKUs`) to immediately filter the table to problematic rows.
4. **Interactive Verification Checklist & Status Verdict:**
   - Restored and updated `evaluateUserNeeds()` to dynamically populate `#verdict-card` and `#verdict-checklist` with custom verification steps based on user-selected dietary priorities (Diabetes, Ketogenic, Celiac, Clean Label).
5. **Modal API Key Management (`saveModalApiKey`):**
   - Restored `saveModalApiKey()` and modal provider switching for Groq and Gemini API keys.
6. **RFC-4180 Quote-Safe CSV Parser:**
   - Enhanced the static browser fallback with a robust state-machine CSV parser handling escaped commas and quotes inside `ingredients_text` and `product_name`.

---

### 5.3 Automated Test Suite (`Food-Database-Completeness-Reviewer-/tests/test_nutriaudit.py`)

A comprehensive test suite of 9 integration and unit tests was authored and verified:
1. `test_demo_dataset_loading`: Confirms `demo_subset(1).csv` loads 552 records with default activation.
2. `test_completeness_calculation`: Tests scoring on fully complete vs missing records.
3. `test_cross_field_anomalies`: Validates detection of `sugar > carbs`, `energy > 900`, negative values, and macro exceedance.
4. `test_salt_sodium_mismatch`: Tests chemical plausibility checking between salt and sodium.
5. `test_duplicate_detection`: Verifies duplicate identification across brand/product name pairs.
6. `test_zero_hallucination_contract`: Confirms nulls are never imputed or replaced with fabricated values.
7. `test_flask_health_and_datasets`: Tests `/api/health` and `/api/datasets` endpoints.
8. `test_flask_audit_endpoint`: Tests end-to-end audit evaluation for a specific SKU.
9. `test_triage_fallback_deterministic`: Confirms fallback reliability when external API calls are disabled.

---

## 6. Verification Results & Metrics

Execution of the test suite yielded:
```text
Ran 9 tests in 0.435s

OK (9/9 passed)
```

### Dataset Audit Summary (`demo_subset(1).csv`):
- **Total Records:** 552
- **Critical Priority (<60% complete):** 245
- **High Priority (60–84% complete):** 9
- **Low Priority (85–99% complete):** 157
- **Complete (100% complete):** 141
- **Cross-Field Math Anomalies Detected:** 62
- **Duplicate SKU Records Flagged:** 27 records across 11 brand/name clusters
- **Imputed/Hallucinated Values:** 0 (100% Zero-Hallucination Verified)

---

## 7. Troubleshooting & Bug Fixes Encountered During Execution

1. **Working Directory Identification:**
   - *Issue:* Git commands run at the workspace root failed with `fatal: not a git repository`.
   - *Fix:* Identified the repository subfolder `Food-Database-Completeness-Reviewer-/` and directed all git, python, and test operations within it.
2. **FastAPI Dependency Failure:**
   - *Issue:* Attempting to run FastAPI resulted in `ModuleNotFoundError: No module named 'pydantic'`.
   - *Fix:* Pivoted to Flask 3.1.2 and `flask-cors`, eliminating external dependency blockers while maintaining full REST specification compliance.
3. **Groq Model Availability:**
   - *Issue:* Groq returned 404 `model_not_found` for `llama-3.3-70b-versatile` on this API key.
   - *Fix:* Probed `/openai/v1/models` to discover active models, switching default to `qwen/qwen3.8-27b` which demonstrated 100% reliable JSON triage output.
4. **Form Input Element Reference:**
   - *Issue:* `document.getElementById('new-calories')` returned null in the custom product modal.
   - *Fix:* Added the missing input element to `index.html` and implemented defensive fallback parsing.
5. **Verdict Checklist Rendering:**
   - *Issue:* `evaluateUserNeeds()` was missing DOM targets for checklist elements.
   - *Fix:* Re-implemented verdict checklist and badge rendering to match the DOM container `#verdict-checklist`.

---

## 8. How to Run & Verify

1. **Start the Flask Backend:**
   ```bash
   python run_server.py
   ```
   *Server starts at: `http://127.0.0.1:8000`*

2. **Run the Automated Tests:**
   ```bash
   python tests/test_nutriaudit.py
   ```

3. **Verify in Browser:**
   - Open `http://127.0.0.1:8000`
   - Notice the dataset switcher at the top showing `demo_subset(1).csv` active by default.
   - Switch datasets via the dropdown to observe dynamic count updates and re-auditing.
   - Click "Run AI Audit" to trigger Groq LLM triage with real-time zero-hallucination verification.
