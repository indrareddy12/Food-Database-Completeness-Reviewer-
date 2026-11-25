# NutriAudit: Food Database Completeness Reviewer (PS 134)

[![Aesthetic](https://img.shields.io/badge/Aesthetic-Organic_Neo--Brutalism-FFD97D?style=for-the-badge&logoColor=18181B)](https://dribbble.com)
[![GenAI](https://img.shields.io/badge/GenAI-Groq%20%26%20Gemini-C7F464?style=for-the-badge&logoColor=18181B)](https://console.groq.com/)
[![VectorDB](https://img.shields.io/badge/Vector_DB-Pinecone_Ready-A5F3FC?style=for-the-badge&logoColor=18181B)](https://pinecone.io)
[![Backend](https://img.shields.io/badge/Backend-Python_Flask_REST-FF9E7D?style=for-the-badge&logoColor=18181B)](https://flask.palletsprojects.com/)
[![Zero-Hallucination](https://img.shields.io/badge/Zero--Hallucination-Contract_Active-22C55E?style=for-the-badge&logoColor=FFFFFF)](README.md)

An agentic, zero-hallucination GenAI audit platform for Problem Statement 134 ("Food Database Completeness Reviewer"). It ingests food nutrition and ingredient records, instantly identifies missing data fields with triage review priorities, visualizes transparency on an animated **Safety Speed Dial**, evaluates items against personal health goals (Gym / Daily Health), flags mathematical & chemical cross-field contradictions, detects duplicate SKU entries, and matches verified database alternatives—**never inventing missing values**.

---

## 🔒 The Zero-Hallucination Core Contract
> **CRITICAL DIRECTIVE:** The system and all GenAI prompts **never invent, guess, estimate, or impute missing ingredients, allergens, or nutritional numbers**.
> When a record lacks an ingredient list, calorie count, protein metric, or allergen declaration, the system **must** label the field explicitly as `MISSING`.
> Hypothetical data interpolation is strictly rejected to prevent adverse consumer health consequences (e.g., assuming a product is peanut-free because nuts are not explicitly mentioned).

---

## 📊 Datasets & Smooth Dataset Toggle

The application defaults to `demo_subset(1).csv` (552 rows) and provides an instant one-click toggle in the UI and backend API:

| Dataset | File Target | Rows | Default Status |
| :--- | :--- | :--- | :--- |
| **Demo Subset** | `demo_subset(1).csv` | **552** | **Default on load** (Ready out of the box) |
| **Full Preprocessed Catalog** | `preprocessed_full(1).csv` | **16,091** | Auto-detected if present in workspace |
| **Synthetic 2,000 Dataset** | `food_completeness_dataset_2000.xlsx` (`Products` sheet) | **2,000** | Auto-detected if present in workspace |

* Switching the toggle immediately reloads/re-audits records, updates global counts, refreshes dropdown selectors/lists, and clears stale AI output from previously inspected items.
* **Direct File Upload:** You can upload `preprocessed_full(1).csv` or `food_completeness_dataset_2000.xlsx` directly from the UI header to enable instant switching.
* `image_url` is completely ignored—no images are rendered and no image/OCR dependencies are required.

---

## ⚙️ Architecture & Backend Modules

### 1. `backend/data_connector.py`
- Loads active dataset (`demo_subset(1).csv` by default) and caches normalized records in memory.
- Normalizes schemas from Open Food Facts CSVs (`energy_kcal_100g`, `proteins_100g`, `sodium_100g`, etc.) and synthetic Excel sheets (`serving_size_g`, `energy_kcal`, `sodium_mg`, etc.).
- Converts `sodium_100g` from grams to `sodium_mg` (`sodium_g * 1000`).
- **Pinecone-Ready Connector:** Clean interface (`get_records(dataset_key)`, `get_similar_records(code, dataset_key)`) that works locally out-of-the-box and stages query routing for Pinecone when `PINECONE_API_KEY` and `PINECONE_INDEX` are configured.

### 2. `backend/validator.py`
- Deterministically detects missing fields across Critical (`ingredients`, `allergens`), High (`calories`, `protein_g`, `sugar_g`, `sodium_mg`), and Low (`carbs_g`, `fat_g`, `fiber_g`, `serving_size`) tiers.
- Computes completeness score (0–100%) and Safety Speed Dial score (0–100).
- Flags duplicate `(product_name, brand)` pairs across the dataset.
- **Flags 7 Numeric & Cross-Field Contradictions:**
  1. Negative values (`< 0`)
  2. Concentrations `> 100g` per 100g baseline
  3. Energy density `> 900 kcal/100g` (exceeds theoretical maximum of pure dietary fat)
  4. Added sugars `> total sugars`
  5. Total sugars `> total carbohydrates`
  6. Saturated fat `> total fat`
  7. Salt / Sodium contradictions (`sodium > salt` or salt/sodium chemical ratio mismatch)

### 3. `backend/triage_service.py`
- Leverages Groq (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`, `llama-3.3-70b-versatile`) or Google Gemini (`gemini-2.5-flash`) with strict zero-hallucination instructions.
- Reads `GROQ_API_KEY` automatically from `.env`.
- Assigns triage review priority, explains why review is needed, and provides step-by-step verification guidance for human QA auditors.
- Includes safe deterministic fallback when offline or if keys are not set.

### 4. `backend/main.py`
- Clean REST API with CORS support, serving both API endpoints and the Neo-Brutalist frontend.
- Routes:
  - `GET /api/health` — Status and configuration health check
  - `GET /api/datasets` — Dataset availability and metadata
  - `POST /api/datasets/active` — Switch active dataset
  - `POST /api/datasets/upload` — Direct dataset upload
  - `GET /api/records` — Filtered/paginated records with dataset statistics
  - `GET /api/records/<id>` — Record detail with audit, anomalies, duplicates, and similar products
  - `POST /api/audit/<id>` — GenAI Deep Audit
  - `POST /api/records` — Add custom product and audit deterministically
  - `GET /` — Serves `index.html`

---

## 🚀 Quickstart & How to Run

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment
Copy `.env.example` to `.env` (or use existing `.env`):
```bash
GROQ_API_KEY=your_groq_api_key_here
```

### Step 3: Run the Server
```bash
python run_server.py
```
Open your browser and navigate to:
```
http://localhost:8000
```

### Step 4: Run Integration Tests
```bash
python tests/test_nutriaudit.py
```

---

## 🎨 UI/UX Features
- **Organic Neo-Brutalism:** High-contrast `2.5px solid #18181B` ink borders, offset drop shadows (`3px` to `5px`), and friendly food pastels (Butter, Matcha, Peach, Lilac, Berry, Sky Mint).
- **Interactive Dataset Toggle:** Seamless one-click switching between Demo Subset, Full Catalog, and Synthetic datasets with status badges.
- **Safety Speed Dial Meter:** Smooth animated semicircular gauge with dynamic risk grade.
- **Cross-Field Math Anomalies & Duplicate Alert Card:** Highlights mathematical contradictions with severity tags.
- **Fixed Add Record Modal:** Full form input set including `new-calories` with immediate deterministic re-scan.
- **Client-Side Standalone Fallback:** Degrades gracefully if `index.html` is opened directly via `file:///` without a running backend.
