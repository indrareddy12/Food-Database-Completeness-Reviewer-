# Dev 3 Brief: GenAI Deep Auditor (Gemini / Groq) & Pinecone Vector Staging

## Role Summary
You own the **AI layer, API key management, zero-hallucination prompt engineering, and Pinecone vector database staging**.

---

## Your Core Responsibilities
1. **Top-Level API Key Controller (`#top-api-key-btn` & `#api-key-modal`)**
   - Keep the `🔑 API Key` pill visible in the top header on all tabs (PC & mobile) with a live status dot (🟢 active / 🟡 not configured).
   - Support switching between **Google Gemini (AI Studio)** and **Groq Cloud** (`llama-3.3-70b-versatile`), syncing with `localStorage` and the Settings tab (`#view-settings`).

2. **Zero-Hallucination Prompt & API Calls (`runAIDeepReview()`)**
   - Implement `callGeminiWithBackoff(promptText)` and `callGroqWithBackoff(promptText)` with exponential backoff and clear user-facing error cards.
   - Enforce strict system instructions:
     > *"NEVER invent, guess, or estimate any missing ingredient, allergen, or nutrition value. Any null/empty field MUST be explicitly reported as MISSING / UNVERIFIED."*
   - Feed the deterministic `auditProduct()` summary + raw JSON record + user health target into the prompt so the LLM generates:
     1. Missing Fields & Review Priority Action Plan
     2. Safety & Allergen Risk Assessment (strictly from recorded data)
     3. Suitability note for the user's stated goal

3. **Environment & Pinecone Vector DB Staging**
   - Maintain `.env.example` and `.gitignore` so no API keys are ever committed.
   - Document and stage the Pinecone index schema (`food-database-completeness`, metadata fields `completeness_score`, `review_priority`, `has_missing_critical`, `allergens`) for semantic supplement matching and cross-allergen clustering in Phase 2.

---

## Acceptance Checklist
- [ ] Clicking `🔑 API Key` in the top header opens the modal and updates the status dot upon saving a Gemini or Groq key.
- [ ] Running `GenAI Deep Audit` on `PROD-101` explicitly reports `ingredients`, `allergens`, `sugar_g`, and `sodium_mg` as `MISSING / UNVERIFIED` without guessing values.
- [ ] Invalid or missing API keys surface a clean error card with a one-click button back to the API Key modal.
- [ ] `.env` remains untracked in `.gitignore`.
