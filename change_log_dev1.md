# dev1_audit_engine — Change Log

**Role:** Dev 1 — Data & Deterministic Audit Lead (`docs/DEV1_AUDIT_ENGINE.md`)  
**Scope:** Data Schema, Completeness Scoring, Review Priority Engine, Dietary Needs Evaluator, and Database Supplement Matcher  
**Date:** 2026-11-25  

---

## 1. Summary of Responsibilities & Deliverables
Dev 1 owns the **source of truth** for food records, deterministic completeness scoring, safety penalties, dietary needs matching, and database-grounded supplement recommendations. Dev 1 strictly enforces the **Zero-Hallucination Directive**: missing data must never be imputed, guessed, or masked.

---

## 2. Key Modules & Implementations

### 2.1 Standardized Food Data Contract (`FoodRecord`)
- Standardized product structure with strictly typed attributes (`id`, `name`, `brand`, `category`, `serving_size`, `calories`, `protein_g`, `carbs_g`, `sugar_g`, `fat_g`, `fiber_g`, `sodium_mg`, `ingredients`, `allergens`, `icon`, `iconColor`).
- Enforced strict `null` representation: any unverified or missing value is stored as `null` or `[]`—never filled with default or assumed numeric zeros.
- Seeded `foodDatabase` in `index.html` with realistic records covering every completeness tier:
  * `PROD-101` (Critical): Missing `ingredients` and `allergens`.
  * `PROD-102` (High Priority): Missing `serving_size`, `calories`, `sugar_g`, and `sodium_mg`.
  * `PROD-103` (Verified Complete): 100% complete nutrition and clean allergen declaration.
  * `PROD-104` to `PROD-108`: Additional edge cases (keto bars, plant milks, organic broths, energy snacks).

### 2.2 Deterministic 10-Field Audit Schema (`REQUIRED_FIELDS`)
Implemented weighted penalty scoring reflecting clinical and regulatory criticality:
- **CRITICAL Severity (-52 pts total):**
  * `ingredients`: `-28 pts` (Safety Hazard: severe allergen / adulteration risk if absent).
  * `allergens`: `-24 pts` (Safety Hazard: critical consumer disclosure requirement).
- **HIGH Severity (-39 pts total):**
  * `serving_size`: `-10 pts` (Portion ambiguity prevents dosage/intake calculation).
  * `calories`: `-8 pts` (Core energetic basis missing).
  * `protein_g`: `-7 pts` (Key macronutrient missing).
  * `sugar_g`: `-7 pts` (Metabolic and diabetic risk factor missing).
  * `sodium_mg`: `-7 pts` (Cardiovascular and hypertension risk factor missing).
- **MEDIUM Severity (-6 pts total):**
  * `carbs_g`: `-3 pts` (Secondary macronutrient missing).
  * `fat_g`: `-3 pts` (Secondary macronutrient missing).
- **LOW Severity (-3 pts total):**
  * `fiber_g`: `-3 pts` (Digestive metric missing).

### 2.3 Deterministic Audit Engine (`auditProduct`)
- **Missing Value Detection (`isFieldMissing`):**
  * Flags `null`, `undefined`, empty string `""`, whitespace-only strings, and empty arrays `[]`.
- **Metrics Computed:**
  * `completenessPct`: Exact percentage of verified fields present $\left(\frac{\text{present fields}}{\text{total fields}} \times 100\right)$.
  * `totalPenalty`: Sum of penalties for all missing fields.
  * `safetyScore`: Bound strictly between 0 and 100:
    $$\text{safetyScore} = \max(0, 100 - \text{totalPenalty})$$
  * `priority`: Ranked categorically based on the highest missing severity:
    * `CRITICAL`: Any missing Critical field (`ingredients` or `allergens`).
    * `HIGH`: Any missing High-severity field (`serving_size`, `calories`, `protein_g`, etc.).
    * `MEDIUM`: Missing Medium/Low fields only.
    * `COMPLETE`: Zero missing fields.
  * `missingFields`: Detailed list with `key`, `label`, `severity`, and consumer safety rationale.

### 2.4 Personal Dietary Needs Evaluator (`evaluateUserNeeds`)
- Evaluates individual suitability against user profiles (`gym`, `daily`, `weightloss`, `clean`) or custom numeric targets (`target-protein`, `target-sugar`, `target-sodium`).
- **Zero-Hallucination Tri-State Verdict:**
  * `PASS`: Product explicitly meets the nutritional target based on verified data.
  * `FAIL`: Product explicitly violates the nutritional threshold.
  * `UNKNOWN`: When the target nutrient is `null` or missing, the evaluator outputs `UNKNOWN` with a caution alert. The system **never assumes compliance** when data is absent.

### 2.5 Grounded Database Supplement Matcher (`renderDatabaseSupplement`)
- Solves missing nutritional profiles or target deficits by recommending verified items strictly from the existing `foodDatabase`.
- Requirements for recommendation:
  * Minimum safety score $\ge 80$.
  * Zero missing Critical fields (`ingredients` and `allergens` must be verified).
  * Explicit complement to the user's deficit (e.g., high protein snack for low-protein primary item).
- If no database item qualifies, outputs an explicit `"No verified database complement found"` rather than hallucinating an external item.

### 2.6 Dynamic Record Ingestion (`handleAddProduct`)
- Handles user-submitted food records.
- Converts blank or whitespace inputs strictly into `null`, ensuring newly ingested records can be tested with missing fields in real time.
- Integrated `#new-calories` input binding alongside macros and allergen declarations.

---

## 3. Verification & Acceptance Checklist
- [x] Missing `ingredients` or `allergens` unconditionally forces `CRITICAL` review priority.
- [x] `safetyScore` is strictly bounded between `0` and `100`.
- [x] Dietary needs evaluation outputs `UNKNOWN` for missing target nutrients (zero assumption of compliance).
- [x] Supplement matcher only suggests verified records from `foodDatabase`.
- [x] Form submission preserves empty inputs as `null` for real-time audit verification.

---

## 4. Full-Stack Backend, Pinecone Integration & Security Hardening (`dharshan` Branch)

Consolidated from `Changelog_dev1.md` (removed to avoid Windows NTFS case collision with `change_log_dev1.md` from `origin/main` `d337352`).

### 4.1 Full-Stack Architecture & Multi-Dataset Support
- **`backend/validator.py`**: Canonical `MISSING_TOKENS` (`""`, `"null"`, `"none"`, `"nan"`, `"undefined"`, `"missing"`, `"unknown"`, `"na"`, `"n/a"`, `"tbd"`, `"-"`, `"?"`, `"[]"`), placeholder-only list & `math.isfinite()` / `bool` guards, duplicate `(name, brand)` SKU detection, and 7 deterministic cross-field anomaly checks (`negative_value`, `macro_exceeds_100g`, `excessive_calories`, `added_sugars_exceed_sugars`, `sugars_exceed_carbs`, `saturated_fat_exceeds_fat`, `sodium_exceeds_salt` / `salt_sodium_mismatch`).
- **`backend/data_connector.py`**: Unified normalizer & manager for `demo` (`food-db-reviewer/demo_subset.csv`, 552 rows), `full` (`preprocessed_full(1).csv`, 16,091 rows), and `synthetic` (`food_completeness_dataset_2000.xlsx` `Products` sheet, 2,000 rows), strictly preserving missing metadata and absent `salt_g` as `None`, plus `assign_food_icon()` Lucide icon mapping.
- **`backend/triage_service.py`**: Groq Cloud (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `llama-3.3-70b-versatile`) & Gemini (`gemini-2.5-flash`) Zero-Hallucination triage with structured logging and explicit `warnings` / `fallback_reason` reporting.
- **`backend/main.py` & `run_server.py`**: Flask REST API (`/api/health`, `/api/datasets`, `/api/datasets/active`, `/api/datasets/upload`, `/api/records`, `/api/records/<id>`, `/api/audit/<id>`, `/api/pinecone/status`, `/api/pinecone/search`) with CORS and `.env` loading.
- **`index.html`**: Unified Dev 2 Lucide icon UI with PS 134 dataset switcher, diagnostic cards, `#new-calories` fix, `Number.isFinite` & list guards, backend REST sync, and RFC-4180 client-side CSV fallback.

### 4.2 Security & Pre-Merge Review Fixes Resolved
1. **Windows Case-Collision (`Changelog_dev1.md` vs `change_log_dev1.md`) — RESOLVED:** Removed `Changelog_dev1.md`, merged `origin/main` (`d337352`), and consolidated all Dev 1 history into lowercase `change_log_dev1.md`.
2. **Secret / Source Exposure via `serve_static` (`backend/main.py`) — RESOLVED:** Replaced open root static fallback with strict `ALLOWED_STATIC_FILES` allowlist and explicit `403 Forbidden` rejection for dotfiles (`.env*`, `.git*`), `..` traversal, and `backend/`, `tests/`, `uploads/`, `docs/` paths.
3. **Upload Path Traversal Hardening (`backend/main.py`) — RESOLVED:** Enforced `werkzeug.utils.secure_filename()`, `{".csv", ".xlsx"}` extension allowlist, and isolated storage in `uploads/` (gitignored).
4. **Duplicate CSV Asset & Port Consistency — RESOLVED:** Removed duplicate root `demo_subset(1).csv` in favor of `food-db-reviewer/demo_subset.csv`; aligned `.env.example` default `PORT=8000` with `run_server.py` and `index.html`.
5. **Dependencies (`requirements.txt`) — RESOLVED:** Added `flask>=3.0.0`, `flask-cors>=4.0.0`, `werkzeug>=3.0.0`, `requests>=2.31.0`, `python-dotenv>=1.0.0`, `openpyxl>=3.1.2`, `pandas>=2.2.0`, `pinecone>=6.0.0`, `pydantic>=2.0.0`.

### 4.3 Live Pinecone Vector DB Integration & Verification
- Connected `backend/data_connector.py` (`get_pinecone_status()`, `query_pinecone_similar()`, `get_similar_records()`) and `index.html` (`updatePineconeStatusUI()`, `renderDatabaseSupplement()`) to live index `food-database-completeness` (`namespace: "food-products"`, `multilingual-e5-large`, `dimension: 1024`, `total_vector_count: 16091`) with `is_verified_safe` metadata filtering and automatic local similarity fallback.
- Verified `tests/test_nutriaudit.py` offline test suite (`10/10` passing, including `serve_static` `403` secret-exposure checks and mocked Pinecone normalization) and live Pinecone endpoints.

### 4.4 Database UI Streamlining, Pagination & Deep Audit Math/Chemical Checks
- **Database Filter Cleanup (`index.html`):** Removed `All`, `Complete`, `Math Anomalies`, and header duplicate badges (`#db-duplicates-banner`, `#top-api-key-btn`) and product card `Math`/`Dup` badges. Streamlined `#filter-pills` to **Critical**, **High**, and **Duplicates** (`activeFilter` defaults to `'CRITICAL'`).
- **Dataset Dropdown & Settings Status Consolidation (`index.html`):** Replaced the Active Dataset toggle buttons with `<select id="dataset-select">` (`updateDatasetBadgesUI()`, `switchDataset()`), and consolidated live **Flask API Backend** (`#backend-conn-badge`) and **Groq / Gemini LLM Triage Engine** (`#settings-groq-text`) status checks into the **Settings** tab (`#view-settings`) with a manual **Re-Check Status** control.
- **Paginated Database Grid (`index.html`):** Replaced the static 120-record slice with client-side pagination (`PAGE_SIZE = 12`, `#db-pagination`, `renderPagination()`, `goToPage()`) across all filtered results.
- **On-Demand Math & Chemical Checks Injected on Deep Audit (`backend/validator.py`, `backend/triage_service.py`, `backend/main.py`, `index.html`):**
  - Added `audit_math_and_chemical_checks()` in `backend/validator.py` and `runMathAndChemicalChecks()` in `index.html` covering numeric contradictions, Atwater energy balance (`4*P + 4*C + 9*F`), macronutrient mass sum (`>105g/100g`), `NaCl` salt/sodium stoichiometry, additive/E-number/sweetener/preservative/hydrogenated-oil scanning, and ingredient-vs-allergen cross-checks under the Zero-Hallucination Contract.
  - Triggered dynamically when clicking **GenAI Deep Audit** (`/api/audit/<record_id>` and `runAIDeepReview()`), injecting `ON-DEMAND MATHEMATICAL VERIFICATION CHECKS` and `ON-DEMAND CHEMICAL & INGREDIENT SAFETY CHECKS` into `build_audit_prompt()`, `run_triage_audit()`, and the `#anomalies-card` verification panel.
- **Verification (`tests/test_nutriaudit.py`):** Added `test_deep_audit_math_and_chemical_prompt_injection` and updated frontend UI assertions (`test_frontend_lucide_icons_and_dataset_toggle`); `python -m pytest -q` passed `11/11`.
