# NutriAudit — Main Project Changelog & Architecture Log

> **Food Database Completeness Reviewer**  
> A hackathon-ready GenAI application designed to audit food and ingredient databases for missing nutrients, allergens, and labels with a **strict Zero-Hallucination guarantee**.

---

## 1. Project Overview & Architectural Principles

NutriAudit processes product nutrition and ingredient records, producing a granular list of incomplete fields, safety penalties, and human review priorities.

### The Zero-Hallucination Contract
1. **Never Invent Data:** The system will **never** synthesize, impute, or guess missing ingredient, allergen, or nutritional values.
2. **Explicit Uncertainty:** Any unverified, empty, or absent field is marked as `MISSING`, `UNVERIFIED`, or `UNKNOWN`.
3. **Clinical Priority Hierarchy:** Missing allergens or ingredients are classified as `CRITICAL` safety hazards and penalize the safety score severely.
4. **Grounded Retrieval:** Recommendations and semantic vector search only return verified records from audited datasets.

---

## 2. Developer Split & Specialized Changelogs

The project architecture is distributed across three specialized developer workstreams:

| Workstream | Lead Role | Key Focus Areas | Developer Changelog |
|---|---|---|---|
| **Dev 1** | Data & Audit Engine | Deterministic 10-field schema, `safetyScore`, `priority`, needs matcher, supplement finder | [change_log_dev1.md](change_log_dev1.md) |
| **Dev 2** | Frontend & UI/UX | Organic Neo-Brutalist design, animated speed dial, 53 Lucide icons, responsive dual nav | [change_log_dev2.md](change_log_dev2.md) |
| **Dev 3** | GenAI & Vector DB | Stage 1 Pydantic validator, CSV auditor, Pinecone vector embeddings (`multilingual-e5-large`) | [change_log_dev3.md](change_log_dev3.md) |

---

## 3. Unified Release History & Merges

### [v1.0.0-review1] — 2026-11-25
**Merge Commit:** `d1728b4` (Merged branch `review-1-food-db-reviewer` into `main`)

#### Key Highlights & Merged Features:
* **Stage 1 Deterministic CSV Auditor (`food-db-reviewer/csv_auditor.py`):**
  - Audits OpenFoodFacts-style CSV datasets across Tier 1 (`ingredients_text`, `allergens`), Tier 2 (10 per-100g nutrients), and Tier 3 (`product_name`, `brands`, `categories`, `serving_size`).
  - Added macro physical sanity check: flags products where Protein + Carbs + Fat $> 105\,\text{g}$ per $100\,\text{g}$.
  - Added calorie-to-macro ratio sanity checks (flags discrepancies where declared calories differ significantly from Atwater calculated energy $4P + 4C + 9F$).
  - Detects negative values, energy $> 900\,\text{kcal}$, and placeholder names where barcode equals product name.
* **Stage 1 JSON Pydantic Validator (`food-db-reviewer/validator.py`):**
  - Robust handling of `NaN`, `+Inf`, and `-Inf` floating point values.
  - Detects filler placeholder lists (e.g., `["none"]`, `["n/a"]`, `["unknown"]`).
  - Emits normalized audit summaries without hallucination.
* **Pinecone Vector Embedding & Semantic Search (`food-db-reviewer/pinecone_ingest.py`):**
  - Ingestion pipeline using Pinecone Inference (`multilingual-e5-large`, 1024 dimensions).
  - Audit-first ingestion: embeds data only after deterministic review; unverified fields are marked `MISSING (Unverified)`.
  - Added empty upsert protection: safely handles and logs empty document sets without throwing errors.
  - Added metadata-filtered semantic querying: `--safe-only` flag restricts search strictly to verified products (`is_verified_safe: true`).
* **UI Dynamic Input Fix (`index.html`):**
  - Integrated the `#new-calories` input element into the Add Record Modal and wired it to `handleAddProduct()`.
* **Audited Demo Dataset (`food-db-reviewer/demo_subset.csv`):**
  - Added 552 verified food records for deterministic testing and reproducible vector index staging.
* **Clean Repo Guard:**
  - Added `PITCH.md` to `.gitignore` to keep pitch documentation decoupled from production code merges.

---

### [v0.3.0-ui] — 2026-11-25
**Commit:** `dd1f455` (Integrated from `feature/likhith_works`)

#### Key Highlights:
* **Organic Neo-Brutalism Design Language:**
  - Dribbble food UI aesthetic with chunky `2.5px solid #18181B` borders, hard offset drop shadows (`3px`–`5px`), and pill geometry.
  - Warm organic pastel palette (`Cream`, `Butter`, `Matcha`, `Peach`, `Lilac`, `Berry`, `Sky Mint`, `Ink`).
* **Lucide Vector Icon System:**
  - Replaced all emojis across the entire client application with 53 crisp Lucide SVG icons.
  - Dynamic `refreshIcons()` lifecycle hook ensures new DOM renders update icons automatically.
* **Interactive Safety Speed Dial:**
  - Smooth animated semicircular SVG gauge (`-90deg` to `+90deg`) visualizing product safety scores in real time.
* **Responsive Dual Navigation:**
  - Desktop sticky pill navigation and mobile floating bottom navigation bar.
* **Header API Key Controller & Modal:**
  - Fast-switching provider support for Google Gemini (AI Studio) and Groq Cloud with live status indicator dot.

---

### [v0.2.0-engine] — 2026-11-25
**Commit:** `07b4f5e` (Initialized Core MVP Engine)

#### Key Highlights:
* **10-Field Deterministic Audit Schema:**
  - Weighted safety penalties: `ingredients` (-28 pts), `allergens` (-24 pts), `serving_size` (-10 pts), `calories` (-8 pts), macros/sugar/sodium (-7 to -3 pts).
* **Tri-State Personal Needs Matcher:**
  - Evaluates user dietary profiles and custom targets against product records.
  - Produces `PASS`, `FAIL`, or `UNKNOWN` (missing target nutrients never assume compliance).
* **Grounded Database Supplement Matcher:**
  - Bridges nutritional deficits by recommending verified items exclusively from the local verified database (score $\ge 80$).

---

### [v0.1.0-init] — 2026-11-25
**Commits:** `718e915`, `e518350`, `fb615d8`

#### Key Highlights:
* Repository initialization with PRD and team architecture plan ([TEAM_WORK_PLAN.md](TEAM_WORK_PLAN.md)).
* Defined developer handoff guides (`docs/DEV1_AUDIT_ENGINE.md`, `docs/DEV2_FRONTEND_UI.md`, `docs/DEV3_GENAI_PINECONE.md`).
* Locked the `FoodRecord` data contract and the zero-hallucination constraint.

---

## 4. Verification & Validation Summary

| Test Suite / Module | Command | Target / Scope | Result |
|---|---|---|---|
| **JSON Record Validator** | `python food-db-reviewer/validator.py` | 5 sample edge-case records | Passed (2 High, 1 Med, 1 Low, 1 Complete) |
| **CSV Integrity Auditor** | `python food-db-reviewer/csv_auditor.py --input food-db-reviewer/demo_subset.csv --summary-only` | 552 OpenFoodFacts records | Passed (90.47% avg completeness, 0 unhandled exceptions) |
| **Pinecone Ingestion** | `python food-db-reviewer/pinecone_ingest.py --input food-db-reviewer/demo_subset.csv --dry-run` | Vector metadata validation | Passed (1024-dim schema compliant) |
| **Client UI Verification** | Browser inspection on `index.html` | Desktop & Mobile views | Passed (53 Lucide icons, 0 layout overflow) |

---

## 5. File & Directory Reference
```
.
├── CHANGELOG.md                   # Main Project Changelog (this file)
├── change_log_dev1.md             # Dev 1 (Audit Engine & Data Schema) Changelog
├── change_log_dev2.md             # Dev 2 (Frontend & UI/UX) Changelog
├── change_log_dev3.md             # Dev 3 (GenAI, Validator & Pinecone) Changelog
├── index.html                     # Client Single-Page Application (HTML/Tailwind/ES6+)
├── TEAM_WORK_PLAN.md              # 3-Developer division of work & contracts
├── docs/
│   ├── DEV1_AUDIT_ENGINE.md       # Dev 1 handoff specifications
│   ├── DEV2_FRONTEND_UI.md        # Dev 2 handoff specifications
│   └── DEV3_GENAI_PINECONE.md     # Dev 3 handoff specifications
└── food-db-reviewer/              # Backend & Vector Reviewer Suite
    ├── README.md                  # GenAI reviewer architecture & CLI docs
    ├── validator.py               # Stage 1 deterministic Pydantic validator
    ├── csv_auditor.py             # OpenFoodFacts CSV database completeness auditor
    ├── pinecone_ingest.py         # Pinecone vector embedding and retrieval pipeline
    ├── demo_subset.csv            # 552 audited sample records
    ├── sample_data.json           # 5 edge-case JSON records
    ├── requirements.txt           # Python dependencies
    └── .env.example               # Environment variables template
```
