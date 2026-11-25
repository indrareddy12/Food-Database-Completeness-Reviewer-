# Dev 1 Brief: Data Schema, Deterministic Audit Engine & Needs Matcher

## Role Summary
You own the **source of truth** for product records, completeness scoring, review priority ranking, user dietary needs evaluation, and database-grounded supplement matching.

---

## Your Core Responsibilities
1. **Product Database & Schema (`foodDatabase` & `REQUIRED_FIELDS`)**
   - Maintain the 10-field audit schema:
     * `CRITICAL`: `ingredients` (-28 pts), `allergens` (-24 pts)
     * `HIGH`: `serving_size` (-10 pts), `calories` (-8 pts), `protein_g` (-7 pts), `sugar_g` (-7 pts), `sodium_mg` (-7 pts)
     * `MEDIUM`: `carbs_g` (-3 pts), `fat_g` (-3 pts)
     * `LOW`: `fiber_g` (-3 pts)
   - Ensure sample records cover all states: `CRITICAL`, `HIGH`, `MEDIUM`, and `COMPLETE`.

2. **Deterministic Audit Engine (`auditProduct(product)`)**
   - Strictly detect missing values via `isFieldMissing(val)` (`null`, `undefined`, empty string, empty array).
   - Compute:
     * `completenessPct` (0–100%)
     * `safetyScore` (`Math.max(0, 100 - totalPenalty)`)
     * `priority` (`CRITICAL` > `HIGH` > `MEDIUM` > `COMPLETE`)
     * `missingFields` array with `key`, `label`, `severity`, and `reason`.
   - **Zero-Hallucination Rule:** Never fill in default macros or guess ingredients.

3. **Personal Needs & Supplement Matcher (`evaluateUserNeeds()`, `renderDatabaseSupplement()`)**
   - Support presets (`gym`, `daily`, `weightloss`, `clean`) + manual user inputs (`target-protein`, `target-sugar`, `target-sodium`, `custom-need-note`).
   - Output `PASS`, `FAIL`, or `UNKNOWN` (if the required nutrient is missing in the record).
   - Recommend top verified alternatives **strictly from `foodDatabase`** (score >= 80 and no critical missing fields), or explicitly state none are available.

4. **Custom Record Ingestion (`handleAddProduct()`)**
   - Parse empty form inputs strictly as `null` so users can test incomplete records live.

---

## Acceptance Checklist
- [ ] Missing `ingredients` or `allergens` always triggers `CRITICAL` priority.
- [ ] `safetyScore` accurately reflects penalties and never exceeds 0–100 bounds.
- [ ] Missing protein/sugar/sodium produces `UNKNOWN` in Needs Evaluator (never `PASS` by assumption).
- [ ] Supplement recommendations only ever return existing `foodDatabase` items.
