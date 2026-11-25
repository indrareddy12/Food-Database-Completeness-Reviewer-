# Food Database Completeness Reviewer (`food-db-reviewer`)

> **Two-Stage Hybrid Pipeline for Safe, Zero-Hallucination Food Data Auditing**  
> **Review 1 Deliverable:** Problem Understanding, Dirty Data Analysis, Architecture Design & Stage 1 Deterministic Validation Skeleton.

---

## 1. Problem Understanding & Zero-Hallucination Constraint

Food and nutrition databases frequently suffer from incomplete, stale, or corrupted product records submitted by manufacturers, scraped from retailers, or entered manually. When downstream consumer apps, dietary tools, or AI assistants process these records, gaps in **ingredients**, **allergens**, or **nutrition metrics** create severe real-world risks:

1. **Life-Threatening Allergen Exposure:** Guessing or omitting an allergen declaration (`nuts`, `milk`, `soy`, `wheat`, etc.) can trigger severe allergic reactions or anaphylaxis.
2. **Regulatory & Labeling Non-Compliance:** Missing or invalid macronutrients (`calories`, `sugar_g`, `sodium_mg`) mislead diabetic, hypertensive, and pediatric consumers.
3. **Silent Data Corruption:** Allowing placeholders (`"N/A"`, `"TBD"`) or impossible numbers (`-150` calories) into analytics silently breaks nutritional scoring.

### The Zero-Hallucination Constraint (Hard Rule)
> **This system MUST NEVER invent, estimate, impute, or hallucinate missing ingredient, allergen, or nutrition values.**

Instead of filling gaps, the reviewer acts strictly as a **triage and audit engine**:
- Every missing or invalid field is explicitly surfaced in `missing_fields` or `invalid_fields`.
- Unknown values remain **unverified** until a human reviewer or authoritative label source supplies them.
- Records with zero gaps **short-circuit** after Stage 1 and never invoke an LLM.

---

## 2. Data Analysis & Field Risk Taxonomy

Every product record is evaluated against 11 schema fields grouped into three risk tiers:

| Risk Tier | Fields | Impact if Missing / Invalid | Baseline Priority Effect |
| :--- | :--- | :--- | :--- |
| **Tier 1: Safety-Critical** | `ingredients`, `allergens` | Immediate consumer health & anaphylaxis risk; impossible to verify dietary safety. | **HIGH** |
| **Tier 2: Regulatory / Nutrition** | `calories`, `protein_g`, `carbs_g`, `fat_g`, `sugar_g`, `sodium_mg` | Breaks nutritional transparency, dietary filtering, and regulatory labeling rules. | **MEDIUM** (escalates to **HIGH** if physically impossible/corrupted, e.g., negative numbers) |
| **Tier 3: Catalog Metadata** | `brand`, `category`, `serving_size` | Reduces catalog searchability and portion context, without hiding direct safety hazards. | **LOW** |
| **Complete Record** | All 11 fields valid | Fully verified baseline data; no gaps detected. | **NONE** (Short-circuits; `needs_llm_review = false`) |

---

## 3. Dirty Data Edge Cases Analyzed

Real-world food catalogs rarely fail cleanly with just `null`. Stage 1 explicitly separates **Missing Fields** from **Invalid Fields**:

- **Missing / Placeholder Values (`missing_fields`):**
  - `null` / `None`
  - Empty or whitespace-only strings (`""`, `"   "`)
  - Placeholder tokens (case-insensitive): `"N/A"`, `"NA"`, `"TBD"`, `"unknown"`, `"null"`, `"none"` (when used as a non-value in numeric fields or unverified placeholder in `ingredients`), `"-"`, `"?"`
  - Empty lists (`[]`) for `ingredients` or `allergens` (Note: an explicit safe declaration like `["None"]` or `["None (Allergen-Free)"]` is valid; `[]` means undeclared/missing)
- **Invalid / Corrupted Values (`invalid_fields`):**
  - **Negative nutrition values:** e.g., `calories: -150` (physically impossible)
  - **Non-numeric strings in numeric fields:** e.g., `protein_g: "unknown"` or `"approx 10g"` (non-placeholder malformed strings, or non-numeric types like booleans)
  - **Malformed list types:** e.g., a number passed for `ingredients` or `allergens`

---

## 4. System Architecture (Two-Stage Hybrid Pipeline)

```text
+-------------------------------------------------------------------------+
|                       Raw Food Record (JSON / CSV)                      |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|              STAGE 1: Deterministic Python / Pydantic Validator         |
|  - Checks Tier 1 (Safety), Tier 2 (Nutrition), Tier 3 (Metadata)        |
|  - Detects null, "", "N/A", "TBD", "unknown", [], negative numbers      |
|  - Assigns deterministic baseline_priority (HIGH / MEDIUM / LOW / NONE) |
+-------------------------------------------------------------------------+
                         |                               |
            0 Gaps Found |                               | >= 1 Gap Found
           (Short-Circuit)                               | (needs_llm_review=true)
                         |                               v
                         |        +---------------------------------------+
                         |        |   STAGE 2: LLM Priority Reviewer      |
                         |        |   - temperature = 0                   |
                         |        |   - Input isolated to audit summary   |
                         |        |   - Strict JSON Schema output ONLY:   |
                         |        |     { priority, reason,               |
                         |        |       action_required }               |
                         |        +---------------------------------------+
                         |                               |
                         +---------------+---------------+
                                         |
                                         v
+-------------------------------------------------------------------------+
|                       NutriAudit Web Dashboard (index.html)               |
|  - Priority Queue (HIGH -> MEDIUM -> LOW) & Verified Catalog            |
|  - Per-field Missing vs. Invalid Breakdown & Reviewer Action Plan       |
+-------------------------------------------------------------------------+
```

---

## 5. Anti-Hallucination Guardrail Strategy

To guarantee the LLM never invents nutrition facts or ingredients in Stage 2:

1. **Input Isolation & Short-Circuiting:**
   - Complete records (`needs_llm_review = false`) bypass the LLM entirely.
   - Incomplete records pass structured gap metadata (`missing_fields`, `invalid_fields`, `baseline_priority`) rather than asking the LLM to "complete the product."
2. **Strict System Prompt Rules:**
   - Explicit prohibition: *"Never estimate, infer, or generate ingredient lists, allergen declarations, or numeric nutrient values. Refer to missing fields strictly as MISSING or UNVERIFIED."*
3. **Deterministic Generation & Strict Output JSON Schema:**
   - `temperature = 0` for reproducible triage.
   - Structured JSON schema restricts LLM output exclusively to three triage fields:
     ```json
     {
       "priority": "HIGH | MEDIUM | LOW",
       "reason": "Concise explanation of why the missing/invalid fields pose risk",
       "action_required": "Specific verification step for the data steward"
     }
     ```
   - Because the schema has no fields for nutrients or ingredients, the model cannot inject fabricated product data into the catalog.

---

## 6. Review 1 Project Files & Verification

```text
food-db-reviewer/
├── README.md            # Problem understanding, taxonomy, architecture & guardrails
├── sample_data.json     # 5 realistic product records covering all dirty-data edge cases
├── validator.py         # Stage 1 deterministic Pydantic validator CLI (JSON)
├── csv_auditor.py       # Stage 1 deterministic CSV database auditor (OpenFoodFacts schema)
├── pinecone_ingest.py   # Audit-first embedding & Pinecone vector database ingestion/query
├── requirements.txt     # Python dependencies (pydantic, pandas, pinecone, python-dotenv)
└── .env.example         # Environment variable template for Pinecone & optional providers
```

### Run Stage 1 Validator (Sample JSON)

```bash
cd food-db-reviewer
python validator.py
```

The script validates every record in `sample_data.json` without modifying or inventing any values and prints a structured JSON audit report containing `missing_fields`, `invalid_fields`, `baseline_priority`, and `needs_llm_review`.

### Run CSV Database Audit & Pinecone Vector Ingestion

```bash
cd food-db-reviewer
pip install -r requirements.txt

# 1. Audit an OpenFoodFacts-style CSV database
python csv_auditor.py --input path/to/food_products.csv --summary-only

# 2. Preview deduplicated embedding texts & Pinecone safety metadata (no API key needed)
python pinecone_ingest.py --input path/to/food_products.csv --dry-run

# 3. Embed (Pinecone multilingual-e5-large) and upsert to Pinecone
#    (Requires PINECONE_API_KEY in .env or environment)
python pinecone_ingest.py --input path/to/food_products.csv --upsert

# 4. Semantic search filtered to verified-safe products only
python pinecone_ingest.py --query "high protein oats without nuts" --safe-only
```
