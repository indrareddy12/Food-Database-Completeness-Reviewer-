# NutriAudit: Food Database Completeness Reviewer

[![Aesthetic](https://img.shields.io/badge/Aesthetic-Organic_Neo--Brutalism-FFD97D?style=for-the-badge&logoColor=18181B)](https://dribbble.com)
[![GenAI](https://img.shields.io/badge/GenAI-Gemini%20%26%20Groq-C7F464?style=for-the-badge&logoColor=18181B)](https://aistudio.google.com/)
[![VectorDB](https://img.shields.io/badge/Vector_DB-Pinecone_Ready-A5F3FC?style=for-the-badge&logoColor=18181B)](https://pinecone.io)
[![License](https://img.shields.io/badge/License-MIT-C4B5FD?style=for-the-badge&logoColor=18181B)](LICENSE)

A clean, resilient, zero-hallucination GenAI application that processes product nutrition and ingredient records, pinpoints incomplete database fields with review priorities, visualizes food transparency on an animated **Safety Speed Dial**, evaluates items against personal dietary goals (Gym / Daily Health), and recommends verified database supplements.

---

## 🔒 The Zero-Hallucination Core Contract
> **Strict Mandate:** This system **never invents, guesses, or estimates missing ingredient or nutrient values**.
> Any omitted data point is explicitly flagged as `MISSING` / `UNVERIFIED` to protect consumer health and prevent safety hazards.

---

## 🎨 UI/UX: Organic Neo-Brutalism (Food UI)
* **Pill-shaped aesthetic:** Pill buttons, chunky `2.5px solid #18181B` ink borders, and hard `3px` to `5px` offset drop shadows.
* **Warm Organic Palette:** Cream (`#FFFDF5`), Butter (`#FFD97D`), Matcha (`#C7F464`), Peach (`#FF9E7D`), Lilac (`#C4B5FD`), Berry (`#FFB3E6`), and Sky Mint (`#A5F3FC`).
* **Responsive Dual Nav:** Floating pill navigation bar on mobile and desktop pill header.

---

## 🚀 Key Features

1. **Top-Level API Key Controller:**
   - Permanent `🔑 API Key` pill button in the top navigation bar with a live status indicator (🟢 Configured / 🟡 Default).
   - Supports both **Google Gemini API** (Google AI Studio) and **Groq Cloud API** (`llama-3.3-70b-versatile`).

2. **Deterministic Completeness & Priority Triaging:**
   - Audits 10 core fields: `ingredients`, `allergens`, `calories`, `protein_g`, `sugar_g`, `sodium_mg`, `carbs_g`, `fat_g`, `fiber_g`, and `serving_size`.
   - Priority classification: `CRITICAL` (missing ingredients/allergens), `HIGH` (missing macros), `MEDIUM`, or `COMPLETE`.

3. **Visual Safety Speed Dial Meter:**
   - Animated semicircular gauge scoring data completeness and transparency from 0 to 100 with dynamic risk categorization (`HIGH RISK`, `MODERATE`, `LOW RISK`).

4. **Personal Health & Dietary Needs Evaluator:**
   - Presets for **🏋️ Gym / High Protein**, **🌿 Daily Basic Health**, **🔥 Low Sugar / Lean**, and **🛡️ Allergen-Safe Clean**.
   - Custom threshold inputs for protein, sugar, sodium, and freeform allergen notes.
   - Visual Suitability Verdict card with expressive mascot indicators and rule-by-rule pass/fail/unknown checklist.

5. **Verified Database Supplement Matcher:**
   - Recommends verified alternatives or supplements strictly from existing database items (never hallucinates imaginary external brands).

6. **Pinecone Vector Database Staging:**
   - Complete vector index schema staged in `PRD.md` for upcoming semantic ingredient embeddings and cross-allergen clustering.

---

## 🛠️ Quickstart (Run in 5 Seconds)

No build tools, bundlers, or package installations required!

### Option 1: Direct Browser Launch
Simply double-click or open `index.html` in any modern web browser:
```bash
# Windows
start index.html

# Mac
open index.html

# Linux
xdg-open index.html
```

### Option 2: Local Static Server (Optional)
```bash
# Using Python
python -m http.server 3000

# Using Node / npx
npx serve .
```
Then navigate to `http://localhost:3000`.

---

## 🔑 Environment Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Insert your API keys (optional — keys can also be entered directly in the web UI via the top header button):
   * `GEMINI_API_KEY`: Get a free key at [Google AI Studio](https://aistudio.google.com/).
   * `GROQ_API_KEY`: Get a key at [Groq Cloud Console](https://console.groq.com/).
   * `PINECONE_API_KEY`: For future vector storage at [Pinecone](https://pinecone.io).

---

## 📄 Documentation
For detailed architecture, data schemas, mathematical penalty models, and roadmap specifications, see:
* [PRD.md](file:///c%3A/THE%20FILE%20OF%20FILES/Programing%20files/Code%20files/gen%20ai%20hackathon/Food-Database-Completeness-Reviewer-/PRD.md)
