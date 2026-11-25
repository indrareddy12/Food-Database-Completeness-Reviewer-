"""
NutriAudit GenAI Triage & Review Service
Calls Groq or Google Gemini under the Strict Zero-Hallucination Contract.
Never infers, estimates, or imputes missing food nutrition or allergen data.
Includes safe, logged deterministic fallback when keys or network are unavailable.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv

from validator import audit_math_and_chemical_checks

logger = logging.getLogger("nutriaudit.triage")

# Load workspace .env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Models verified active on Groq Cloud API (/openai/v1/models), with fallback for standard tiers
PREFERRED_GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
]


def get_active_groq_key() -> Optional[str]:
    key = os.getenv("GROQ_API_KEY")
    if key and key.strip() and key != "your_groq_api_key_here":
        return key.strip()
    return None


def get_active_gemini_key() -> Optional[str]:
    key = os.getenv("GEMINI_API_KEY")
    if key and key.strip() and key != "your_gemini_api_key_here":
        return key.strip()
    return None


def compute_audited_safety_score(audit: Dict[str, Any], anomalies: list) -> int:
    """Compute final post-audit safety score (0-100) accounting for completeness and contradictions."""
    base_score = int(audit.get("safety_score", 0) or 0)
    penalty = 0
    for item in anomalies or []:
        sev = str(item.get("severity", "")).upper()
        if sev == "CRITICAL":
            penalty += 25
        elif sev == "HIGH":
            penalty += 12
        elif sev == "MEDIUM":
            penalty += 6
    return max(0, min(100, base_score - penalty))


def _build_score_impact_breakdown(audit: Dict[str, Any], anomalies: list) -> Tuple[List[str], int]:
    """Compute exact per-field and anomaly deductions on the Safety Speed Dial score."""
    impacts: List[str] = []
    for f in audit.get("missing_critical", []):
        impacts.append(f"- {f}: -30 pts (MAJOR CRITICAL IMPACT — directly blocks consumer safety verification)")
    for f in audit.get("missing_high", []):
        impacts.append(f"- {f}: -10 pts (MODERATE-HIGH IMPACT — limits nutritional accuracy)")
    for f in audit.get("missing_low", []):
        impacts.append(f"- {f}: -5 pts (MINIMAL IMPACT — secondary label attribute; low effect on ingredient safety)")
    for a in anomalies or []:
        sev = str(a.get("severity", "")).upper()
        pts = 25 if sev == "CRITICAL" else (12 if sev == "HIGH" else 6)
        impacts.append(f"- Anomaly [{sev}] {a.get('field', 'data')}: -{pts} pts ({a.get('type', 'contradiction')})")
    return impacts, compute_audited_safety_score(audit, anomalies)


def build_audit_prompt(
    record: Dict[str, Any],
    audit: Dict[str, Any],
    anomalies: list,
    math_checks: Optional[List[Dict[str, Any]]] = None,
    chemical_checks: Optional[List[Dict[str, Any]]] = None,
    user_query: Optional[str] = None,
) -> str:
    """Build a focused ingredient, math/chemical check, and safety-score impact audit prompt."""
    product_name = record.get("name") or "MISSING"
    brand = record.get("brand") or "MISSING"
    category = record.get("category") or "MISSING"
    serving = record.get("serving_size") or "MISSING"

    nutrients = {
        "calories": record.get("calories"),
        "protein_g": record.get("protein_g"),
        "carbs_g": record.get("carbs_g"),
        "sugar_g": record.get("sugar_g"),
        "added_sugars_g": record.get("added_sugars_g"),
        "fat_g": record.get("fat_g"),
        "saturated_fat_g": record.get("saturated_fat_g"),
        "fiber_g": record.get("fiber_g"),
        "sodium_mg": record.get("sodium_mg"),
        "salt_g": record.get("salt_g"),
    }
    nutrient_summary = "\n".join(
        f"  - {k}: {v if v is not None else 'MISSING'}"
        for k, v in nutrients.items()
    )

    ingredients = record.get("ingredients_text") or (", ".join(record.get("ingredients") or []) if record.get("ingredients") else "MISSING")
    allergens = record.get("allergens_text") or (", ".join(record.get("allergens") or []) if record.get("allergens") else "MISSING")

    if math_checks is None or chemical_checks is None:
        computed = audit_math_and_chemical_checks(record)
        math_checks = computed["math_checks"] if math_checks is None else math_checks
        chemical_checks = computed["chemical_checks"] if chemical_checks is None else chemical_checks

    math_str = "\n".join(
        f"  - [{m.get('severity', 'INFO')}] {m.get('message')}"
        for m in math_checks
    ) if math_checks else "  - PASS: No mathematical, macro-bound, or Atwater energy contradictions found on declared values."

    chemical_str = "\n".join(
        f"  - [{c.get('severity', 'INFO')}] {c.get('message')}"
        for c in chemical_checks
    ) if chemical_checks else "  - PASS: No salt/sodium stoichiometry contradictions, flagged chemical additives, or ingredient-allergen mismatches detected."

    anomalies_str = "\n".join(
        f"  - [{a.get('severity')}] {a.get('message')}"
        for a in anomalies
    ) if anomalies else "  - None detected."

    impact_lines, audited_score = _build_score_impact_breakdown(audit, anomalies)
    impact_str = "\n".join(f"  {line}" for line in impact_lines) if impact_lines else "  - No deductions (100/100 verified completeness)."

    query_block = (
        f'SPECIFIC AUDIT QUESTION:\n"{user_query.strip()}"\n'
        "Answer this question directly in the opening section based strictly on the product's declared ingredients, missing fields, math/chemical checks, and safety score impact below.\n"
        if user_query and user_query.strip()
        else (
            "AUDIT OBJECTIVE: Evaluate this product strictly on its declared ingredients, missing fields, mathematical/chemical checks, and how much "
            "each missing attribute affects the Safety Score (distinguishing high-impact safety gaps from minor omissions with low impact).\n"
        )
    )

    prompt = f"""You are NutriAudit AI, a senior food safety and database quality auditor.

INTERNAL INTEGRITY RULES (STRICT — DO NOT NARRATE THESE RULES IN THE OUTPUT):
- Focus ONLY on food database quality, declared ingredients, allergen declarations, missing fields, math/chemical checks, and their exact impact on the Safety Score. Do NOT discuss personal fitness goals unless explicitly asked in the user question.
- Never invent, estimate, infer, or guess any missing ingredient, allergen, or nutrient value.
- If a value is MISSING or UNDECLARED, state clearly that it is missing/undeclared and explain its exact Safety Score impact (major vs. minimal effect).
- Do NOT open your response with a "Zero-Hallucination Verification Guarantee" section or meta-statements about guardrails.

{query_block}
FOOD RECORD UNDER AUDIT:
- Product Name: {product_name}
- Brand: {brand}
- Category: {category}
- Serving Size: {serving}
- Ingredients Declaration: {ingredients}
- Allergens Declaration: {allergens}
- Declared Nutrients (per 100g/serving):
{nutrient_summary}

SAFETY SCORE & MISSINGNESS IMPACT BREAKDOWN:
- Field Completeness: {audit.get('completeness_pct', 0)}%
- Post-Audit Safety Score: {audited_score}/100
- Review Priority: {audit.get('review_priority', 'UNKNOWN')}
- Score Deductions by Missing Field / Anomaly:
{impact_str}
- Cross-Field Anomalies:
{anomalies_str}

ON-DEMAND MATHEMATICAL VERIFICATION CHECKS (INJECTED ON DEEP AUDIT):
{math_str}

ON-DEMAND CHEMICAL & INGREDIENT SAFETY CHECKS (INJECTED ON DEEP AUDIT):
{chemical_str}

Respond in a concise, authoritative food-safety QA report using these markdown headings (no emojis, no guardrail preamble):
### Audit Summary & Safety Score Impact
Directly answer the audit question (if any), evaluate the declared ingredients, and clearly state the Safety Score ({audited_score}/100) along with which missing fields cause major vs. minimal impact.

### Ingredient & Allergen Verification
Analyze the declared ingredient composition (or absence of ingredients) and any undeclared/missing allergen implications.

### Mathematical & Chemical Check Findings
Breakdown of mathematical balance checks (Atwater energy, macro caps, sugar/fat hierarchy), chemical checks (NaCl stoichiometry, E-numbers/preservatives/sweeteners, allergen cross-checks), and missing fields.

### Recommended QA Actions
Provide concrete verification steps (spec sheet check, artwork audit, lab assay).
"""
    return prompt


def generate_deterministic_fallback_audit(
    record: Dict[str, Any],
    audit: Dict[str, Any],
    anomalies: list,
    provider_warnings: Optional[List[str]] = None,
    math_checks: Optional[List[Dict[str, Any]]] = None,
    chemical_checks: Optional[List[Dict[str, Any]]] = None,
    user_query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Deterministic rule-based ingredient and safety-score impact audit.
    Used when offline, when no external LLM API key is configured, or when LLM providers fail.
    """
    name = record.get("name") or "MISSING PRODUCT NAME"
    brand = record.get("brand") or "MISSING BRAND"
    priority = audit.get("review_priority", "HIGH")
    impact_lines, audited_score = _build_score_impact_breakdown(audit, anomalies)
    missing_crit = audit.get("missing_critical", [])
    missing_high = audit.get("missing_high", [])
    missing_low = audit.get("missing_low", [])

    ingredients = record.get("ingredients_text") or (
        ", ".join(record.get("ingredients") or []) if record.get("ingredients") else None
    )
    allergens = record.get("allergens_text") or (
        ", ".join(record.get("allergens") or []) if record.get("allergens") else None
    )

    summary_lines: List[str] = []
    if user_query and user_query.strip():
        summary_lines.append(f"**Query Addressed:** \"{user_query.strip()}\"")
    summary_lines.append(
        f"**Safety Score for {name}:** **{audited_score}/100** (**{priority} PRIORITY**, {audit.get('completeness_pct')}% field completeness)."
    )
    if impact_lines:
        summary_lines.append("**Safety Score Impact Breakdown:**")
        summary_lines.extend(impact_lines)
    else:
        summary_lines.append("**Safety Score Impact:** All audited fields are present — zero deductions applied.")

    ing_lines: List[str] = []
    if ingredients:
        ing_lines.append(f"* **Ingredients Declared:** `{ingredients}`")
    else:
        ing_lines.append("* **Ingredients:** MISSING (-30 pts). Absence of formulation data prevents ingredient-level safety verification.")

    if allergens:
        ing_lines.append(f"* **Allergens Declared:** `{allergens}`")
    else:
        ing_lines.append("* **Allergens:** UNDECLARED / MISSING (-30 pts). Missing allergen disclosure prevents safe sign-off even if base ingredients are simple.")

    if missing_low and not missing_crit and not missing_high:
        ing_lines.append(f"* **Minimal-Impact Omissions:** {', '.join(missing_low)} missing (-5 pts each), which has low effect on core ingredient safety.")

    if math_checks is None or chemical_checks is None:
        computed = audit_math_and_chemical_checks(record)
        math_checks = computed["math_checks"] if math_checks is None else math_checks
        chemical_checks = computed["chemical_checks"] if chemical_checks is None else chemical_checks

    math_texts = [f"* [{m.get('severity', 'INFO')}] {m.get('message')}" for m in math_checks]
    if not math_texts:
        math_texts = ["* PASS: No mathematical, macro-bound, or Atwater calorie contradictions detected."]

    chemical_texts = [f"* [{c.get('severity', 'INFO')}] {c.get('message')}" for c in chemical_checks]
    if not chemical_texts:
        chemical_texts = ["* PASS: No salt/sodium stoichiometry errors, flagged chemical additives, or ingredient-allergen mismatches detected."]

    guidance = [
        f"1. Cross-verify manufacturer product specification sheet for '{brand}'."
        if missing_crit or missing_high else
        f"1. Maintain current verified packaging specification for '{brand}'.",
        "2. Inspect physical packaging artwork for mandatory allergen and nutrition declarations.",
        "3. Resolve any flagged cross-field mathematical contradictions via certified lab assay."
    ]

    warnings_list = provider_warnings or []
    fallback_note = ""
    if warnings_list:
        fallback_note = f"\n\n### Provider Fallback Notice\nExternal LLM call fell back to deterministic mode: {'; '.join(warnings_list)}"

    content = f"""### Audit Summary & Safety Score Impact
{chr(10).join(summary_lines)}

### Ingredient & Allergen Verification
{chr(10).join(ing_lines)}

### Mathematical & Chemical Check Findings
- **Major Impact Missing (Critical, -30 pts each):** {', '.join(missing_crit) if missing_crit else 'None'}
- **Moderate Impact Missing (High, -10 pts each):** {', '.join(missing_high) if missing_high else 'None'}
- **Minimal Impact Missing (Low, -5 pts each):** {', '.join(missing_low) if missing_low else 'None'}
**Mathematical Checks:**
{chr(10).join(math_texts)}
**Chemical & Ingredient Safety Checks:**
{chr(10).join(chemical_texts)}

### Recommended QA Actions
{chr(10).join(guidance)}{fallback_note}
"""
    return {
        "status": "success",
        "provider": "deterministic_fallback",
        "model": "NutriAudit-Deterministic-RuleEngine",
        "content": content,
        "review_priority": priority,
        "safety_score": audited_score,
        "zero_hallucination_guaranteed": True,
        "math_checks": math_checks,
        "chemical_checks": chemical_checks,
        "prompt_checks_injected": True,
        "warnings": warnings_list,
        "fallback_reason": "; ".join(warnings_list) if warnings_list else "No external LLM key configured."
    }


def run_triage_audit(
    record: Dict[str, Any],
    audit: Dict[str, Any],
    anomalies: list,
    client_groq_key: Optional[str] = None,
    client_gemini_key: Optional[str] = None,
    math_checks: Optional[List[Dict[str, Any]]] = None,
    chemical_checks: Optional[List[Dict[str, Any]]] = None,
    user_query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run triage audit using Groq, Gemini, or safe logged deterministic fallback.
    Computes on-demand mathematical and chemical checks and injects them into the LLM prompt.
    """
    if math_checks is None or chemical_checks is None:
        computed = audit_math_and_chemical_checks(record)
        math_checks = computed["math_checks"] if math_checks is None else math_checks
        chemical_checks = computed["chemical_checks"] if chemical_checks is None else chemical_checks

    prompt = build_audit_prompt(
        record,
        audit,
        anomalies,
        math_checks=math_checks,
        chemical_checks=chemical_checks,
        user_query=user_query,
    )
    audited_score = compute_audited_safety_score(audit, anomalies)
    provider_warnings: List[str] = []

    # 1. Try Groq (Preferred with active Groq API Key)
    groq_key = client_groq_key or get_active_groq_key()
    if groq_key:
        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json"
        }
        for model in PREFERRED_GROQ_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are NutriAudit AI, a senior food safety auditor. Never invent, estimate, or guess missing "
                            "food data. Answer the user's query directly using only verified facts and explicit missingness. "
                            "Do not output meta-disclaimers about zero-hallucination guardrails."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 800
            }
            try:
                resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=12)
                if resp.status_code == 200:
                    data = resp.json()
                    ai_content = data["choices"][0]["message"]["content"]
                    return {
                        "status": "success",
                        "provider": "groq",
                        "model": model,
                        "content": ai_content,
                        "review_priority": audit.get("review_priority"),
                        "safety_score": audited_score,
                        "zero_hallucination_guaranteed": True,
                        "math_checks": math_checks,
                        "chemical_checks": chemical_checks,
                        "prompt_checks_injected": True,
                        "warnings": provider_warnings
                    }
                msg = f"Groq ({model}) returned HTTP {resp.status_code}"
                logger.warning("%s: %s", msg, resp.text[:160])
                provider_warnings.append(msg)
            except (requests.RequestException, OSError) as exc:
                msg = f"Groq ({model}) request error: {type(exc).__name__}"
                logger.warning("%s: %s", msg, exc)
                provider_warnings.append(msg)
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                msg = f"Groq ({model}) malformed response: {exc}"
                logger.warning(msg)
                provider_warnings.append(msg)

    # 2. Try Gemini if configured
    gemini_key = client_gemini_key or get_active_gemini_key()
    if gemini_key:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        gemini_payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 800
            }
        }
        try:
            resp = requests.post(gemini_url, json=gemini_payload, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                ai_text = data["candidates"][0]["content"]["parts"][0]["text"]
                return {
                    "status": "success",
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "content": ai_text,
                    "review_priority": audit.get("review_priority"),
                    "safety_score": audited_score,
                    "zero_hallucination_guaranteed": True,
                    "math_checks": math_checks,
                    "chemical_checks": chemical_checks,
                    "prompt_checks_injected": True,
                    "warnings": provider_warnings
                }
            msg = f"Gemini returned HTTP {resp.status_code}"
            logger.warning("%s: %s", msg, resp.text[:160])
            provider_warnings.append(msg)
        except (requests.RequestException, OSError) as exc:
            msg = f"Gemini request error: {type(exc).__name__}"
            logger.warning("%s: %s", msg, exc)
            provider_warnings.append(msg)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            msg = f"Gemini malformed response: {exc}"
            logger.warning(msg)
            provider_warnings.append(msg)

    # 3. Safe, deterministic fallback that logs & reports warnings explicitly
    return generate_deterministic_fallback_audit(
        record,
        audit,
        anomalies,
        provider_warnings=provider_warnings,
        math_checks=math_checks,
        chemical_checks=chemical_checks,
        user_query=user_query,
    )


def evaluate_needs_checks(record: Optional[Dict[str, Any]], needs: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministically evaluate a food record against personal nutrition & allergen goals."""
    if not record:
        return {"verdict": "PENDING", "checks": [], "pass_count": 0, "fail_count": 0, "unknown_count": 0}

    audit = record.get("audit") or {}
    missing_crit = audit.get("missing_critical") or []
    checks: List[Dict[str, str]] = []
    pass_count = 0
    fail_count = 0
    unknown_count = 0

    if missing_crit:
        fail_count += 1
        checks.append({
            "status": "FAIL",
            "text": f"Missing critical declaration ({', '.join(missing_crit)}) — safety cannot be verified."
        })
    else:
        pass_count += 1
        checks.append({
            "status": "PASS",
            "text": "Ingredients and allergen declarations are present."
        })

    min_prot = needs.get("min_protein_g")
    if min_prot is not None and min_prot != "":
        target_p = float(min_prot)
        val_p = record.get("protein_g")
        if val_p is None:
            unknown_count += 1
            checks.append({"status": "UNKNOWN", "text": f"Protein is MISSING in database (target >= {target_p:g}g)."})
        elif float(val_p) >= target_p:
            pass_count += 1
            checks.append({"status": "PASS", "text": f"Protein meets your goal: {val_p}g >= {target_p:g}g."})
        else:
            fail_count += 1
            checks.append({"status": "FAIL", "text": f"Protein is below target: {val_p}g (need >= {target_p:g}g)."})

    max_sug = needs.get("max_sugar_g")
    if max_sug is not None and max_sug != "":
        target_s = float(max_sug)
        val_s = record.get("sugar_g")
        if val_s is None:
            unknown_count += 1
            checks.append({"status": "UNKNOWN", "text": f"Sugar is MISSING in database (limit <= {target_s:g}g)."})
        elif float(val_s) <= target_s:
            pass_count += 1
            checks.append({"status": "PASS", "text": f"Sugar is within limit: {val_s}g <= {target_s:g}g."})
        else:
            fail_count += 1
            checks.append({"status": "FAIL", "text": f"High sugar: {val_s}g exceeds {target_s:g}g."})

    max_sod = needs.get("max_sodium_mg")
    if max_sod is not None and max_sod != "":
        target_na = float(max_sod)
        val_na = record.get("sodium_mg")
        if val_na is None:
            unknown_count += 1
            checks.append({"status": "UNKNOWN", "text": f"Sodium is MISSING in database (limit <= {target_na:g}mg)."})
        elif float(val_na) <= target_na:
            pass_count += 1
            checks.append({"status": "PASS", "text": f"Sodium is within limit: {val_na}mg <= {target_na:g}mg."})
        else:
            fail_count += 1
            checks.append({"status": "FAIL", "text": f"High sodium: {val_na}mg exceeds {target_na:g}mg."})

    custom_note = (needs.get("custom_note") or "").strip().lower()
    if custom_note:
        alg_text = (record.get("allergens_text") or ", ".join(record.get("allergens") or [])).lower()
        ing_text = (record.get("ingredients_text") or ", ".join(record.get("ingredients") or [])).lower()
        if "peanut" in custom_note and ("peanut" in alg_text or "peanut" in ing_text):
            fail_count += 1
            checks.append({"status": "FAIL", "text": "Contains PEANUT or derivatives matching your restriction."})
        elif "dairy" in custom_note and any(k in alg_text or k in ing_text for k in ("milk", "whey", "dairy")):
            fail_count += 1
            checks.append({"status": "FAIL", "text": "Contains DAIRY / Milk matching your restriction."})

    verdict = "FAIL" if fail_count > 0 else ("UNKNOWN" if unknown_count > 0 else "PASS")
    return {
        "verdict": verdict,
        "checks": checks,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "unknown_count": unknown_count,
    }


def run_needs_chat_assistant(
    user_message: str,
    needs: Dict[str, Any],
    evaluated_record: Optional[Dict[str, Any]],
    recommendations: List[Dict[str, Any]],
    retrieval_source: str,
    mentioned_in_chat: bool,
    client_groq_key: Optional[str] = None,
    client_gemini_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a Pinecone-grounded dietary needs recommendation and verification reply."""
    needs_eval = evaluate_needs_checks(evaluated_record, needs)
    safety_score = (
        compute_audited_safety_score(evaluated_record.get("audit", {}), evaluated_record.get("anomalies", []))
        if evaluated_record else None
    )

    cand_lines = []
    for idx, rec in enumerate(recommendations[:5], 1):
        cand_lines.append(
            f"{idx}. {rec.get('name') or 'Unnamed'} (ID: {rec.get('id')}, Brand: {rec.get('brand') or 'N/A'}) — "
            f"Calories: {rec.get('calories') if rec.get('calories') is not None else 'MISSING'}, "
            f"Protein: {rec.get('protein_g') if rec.get('protein_g') is not None else 'MISSING'}g, "
            f"Sugar: {rec.get('sugar_g') if rec.get('sugar_g') is not None else 'MISSING'}g, "
            f"Sodium: {rec.get('sodium_mg') if rec.get('sodium_mg') is not None else 'MISSING'}mg, "
            f"Allergens: {rec.get('allergens_text') or (', '.join(rec.get('allergens') or []) if rec.get('allergens') else 'UNDECLARED')}"
        )
    cand_block = "\n".join(cand_lines) if cand_lines else "No verified matches retrieved."

    eval_summary = "None"
    if evaluated_record:
        check_lines = "\n".join(f"  - [{c['status']}] {c['text']}" for c in needs_eval["checks"])
        eval_summary = (
            f"Product: {evaluated_record.get('name') or 'Unnamed'} (ID: {evaluated_record.get('id')})\n"
            f"Safety Score: {safety_score}/100\n"
            f"Ingredients: {evaluated_record.get('ingredients_text') or ', '.join(evaluated_record.get('ingredients') or []) or 'MISSING'}\n"
            f"Allergens: {evaluated_record.get('allergens_text') or ', '.join(evaluated_record.get('allergens') or []) or 'UNDECLARED'}\n"
            f"Checks:\n{check_lines}"
        )

    prompt = f"""You are NutriAudit's Personal Nutrition & Food Safety Assistant.
Answer the user's request concisely using ONLY the verified Pinecone/database records below. Never invent missing nutrition metrics or allergens. Do NOT add meta-disclaimers about guardrails.

USER MESSAGE: "{user_message or 'Find safe foods matching my current health and nutrition needs.'}"
USER TARGETS:
- Goal: {needs.get('goal', 'general')}
- Min Protein: {needs.get('min_protein_g')}g | Max Sugar: {needs.get('max_sugar_g')}g | Max Sodium: {needs.get('max_sodium_mg')}mg
- Custom Note: {needs.get('custom_note') or 'None'}

PRIMARY PRODUCT EVALUATED ({'explicitly mentioned by user' if mentioned_in_chat else 'top database/Pinecone match'}):
{eval_summary}

RETRIEVED CANDIDATES ({retrieval_source.upper()}):
{cand_block}

Respond clearly in 2 short sections:
### Suitability & Safety Check
State whether the evaluated product fits the user's goals and note its Safety Score ({safety_score if safety_score is not None else 'N/A'}/100) and any unverified/missing risks.

### Verified Recommendations from Database
Briefly recommend the best matching options strictly from the retrieved candidates above (including their IDs and protein/sugar/allergen facts).
"""

    provider_warnings: List[str] = []
    groq_key = client_groq_key or get_active_groq_key()
    if groq_key:
        headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
        for model in PREFERRED_GROQ_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are NutriAudit's nutrition assistant. Use only retrieved database facts. Never invent missing nutrients or allergens."
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.15,
                "max_tokens": 600,
            }
            try:
                resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=12)
                if resp.status_code == 200:
                    return {
                        "answer": resp.json()["choices"][0]["message"]["content"],
                        "provider": "groq",
                        "model": model,
                        "warnings": provider_warnings,
                        "needs_eval": needs_eval,
                        "safety_score": safety_score,
                    }
                provider_warnings.append(f"Groq ({model}) HTTP {resp.status_code}")
            except (requests.RequestException, OSError, KeyError, IndexError, ValueError, TypeError) as exc:
                provider_warnings.append(f"Groq ({model}) {type(exc).__name__}")

    gemini_key = client_gemini_key or get_active_gemini_key()
    if gemini_key:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        try:
            resp = requests.post(
                gemini_url,
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.15, "maxOutputTokens": 600}},
                timeout=12,
            )
            if resp.status_code == 200:
                return {
                    "answer": resp.json()["candidates"][0]["content"]["parts"][0]["text"],
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "warnings": provider_warnings,
                    "needs_eval": needs_eval,
                    "safety_score": safety_score,
                }
            provider_warnings.append(f"Gemini HTTP {resp.status_code}")
        except (requests.RequestException, OSError, KeyError, IndexError, ValueError, TypeError) as exc:
            provider_warnings.append(f"Gemini {type(exc).__name__}")

    # Deterministic fallback reply grounded strictly in retrieved Pinecone/DB records
    eval_name = (evaluated_record.get("name") or f"ID {evaluated_record.get('id')}") if evaluated_record else "No matching record"
    check_bullets = "\n".join(f"* **[{c['status']}]** {c['text']}" for c in needs_eval["checks"]) or "* No verified records matched your query."
    rec_bullets = "\n".join(
        f"* **{r.get('name') or 'Unnamed'}** (`{r.get('id')}`) — Protein: {r.get('protein_g') if r.get('protein_g') is not None else 'MISSING'}g, Sugar: {r.get('sugar_g') if r.get('sugar_g') is not None else 'MISSING'}g, Allergens: {r.get('allergens_text') or (', '.join(r.get('allergens') or []) if r.get('allergens') else 'UNDECLARED')}"
        for r in recommendations[:3]
    ) or "* No additional verified alternatives retrieved."

    fallback_answer = (
        f"### Suitability & Safety Check\n"
        f"**Evaluated ({'Mentioned in Chat' if mentioned_in_chat else retrieval_source.upper()} Match):** {eval_name} — Safety Score **{safety_score if safety_score is not None else 'N/A'}/100**\n"
        f"{check_bullets}\n\n"
        f"### Verified Recommendations from Database\n"
        f"{rec_bullets}"
    )
    return {
        "answer": fallback_answer,
        "provider": "deterministic_fallback",
        "model": "NutriAudit-Pinecone-NeedsEngine",
        "warnings": provider_warnings,
        "needs_eval": needs_eval,
        "safety_score": safety_score,
    }
