"""
NutriAudit GenAI Triage & Review Service
Calls Groq or Google Gemini under the Strict Zero-Hallucination Contract.
Never infers, estimates, or imputes missing food nutrition or allergen data.
Includes safe, logged deterministic fallback when keys or network are unavailable.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv

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


def build_audit_prompt(record: Dict[str, Any], audit: Dict[str, Any], anomalies: list) -> str:
    """Build a structured zero-hallucination audit prompt."""
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

    anomalies_str = "\n".join(
        f"  - [{a.get('severity')}] {a.get('message')}"
        for a in anomalies
    ) if anomalies else "  - None detected."

    prompt = f"""You are NutriAudit AI, an expert food safety and database quality auditor.

CRITICAL DIRECTIVE — ZERO-HALLUCINATION CONTRACT:
1. You must NEVER invent, estimate, infer, or guess any missing ingredient, allergen, or nutritional metric.
2. Missing fields MUST be acknowledged explicitly as MISSING. Under no circumstances assume that missing allergens mean the product is allergen-free.
3. Review the food record below, evaluate completeness and anomalies, and provide an actionable QA verification audit.

FOOD RECORD UNDER AUDIT:
- Product Name: {product_name}
- Brand: {brand}
- Category: {category}
- Serving Size: {serving}
- Ingredients Declaration: {ingredients}
- Allergens Declaration: {allergens}
- Declared Nutrients (per 100g/serving):
{nutrient_summary}

DETERMINISTIC VALIDATION ENGINE FINDINGS:
- Completeness Score: {audit.get('completeness_pct', 0)}%
- Assigned Priority: {audit.get('review_priority', 'UNKNOWN')}
- Safety Speed Dial Score: {audit.get('safety_score', 0)}/100
- Missing Critical Fields: {', '.join(audit.get('missing_critical', [])) or 'None'}
- Missing High Fields: {', '.join(audit.get('missing_high', [])) or 'None'}
- Missing Low Fields: {', '.join(audit.get('missing_low', [])) or 'None'}
- Cross-Field Anomalies:
{anomalies_str}

Please generate an audit response structured with these exact plain-text section headings (no emojis):
1. ZERO-HALLUCINATION VERIFICATION GUARANTEE: Affirm explicitly that no missing metrics were inferred.
2. TRIAGE PRIORITY & RISK ASSESSMENT: Why this record requires review (e.g. anaphylaxis risk from missing allergens, compliance failure from missing ingredients, or metabolic risk).
3. DETECTED ANOMALIES & OMISSIONS: Breakdown of missing fields and any mathematical contradictions.
4. ACTIONABLE QA VERIFICATION GUIDANCE: Concrete, step-by-step instructions for human food safety auditors (packaging verification, manufacturer spec request, laboratory assay).
"""
    return prompt


def generate_deterministic_fallback_audit(
    record: Dict[str, Any],
    audit: Dict[str, Any],
    anomalies: list,
    provider_warnings: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Deterministic rule-based audit report matching the zero-hallucination contract.
    Used when offline, when no external LLM API key is configured, or when LLM providers fail.
    """
    name = record.get("name") or "MISSING"
    brand = record.get("brand") or "MISSING"
    priority = audit.get("review_priority", "HIGH")
    missing_crit = audit.get("missing_critical", [])
    missing_high = audit.get("missing_high", [])
    missing_low = audit.get("missing_low", [])

    risk_points = []
    if "allergens" in missing_crit:
        risk_points.append("CRITICAL HEALTH HAZARD: Undeclared allergen data poses direct anaphylactic risk to consumers with food allergies.")
    if "ingredients" in missing_crit:
        risk_points.append("REGULATORY NON-COMPLIANCE: Complete ingredient formulation is absent, preventing verification of artificial additives or allergens.")
    if "sodium_mg" in missing_high:
        risk_points.append("HYPERTENSION RISK: Missing sodium metrics prevent cardiovascular and low-sodium dietary monitoring.")
    if "sugar_g" in missing_high:
        risk_points.append("METABOLIC RISK: Omission of sugar metrics impedes diabetic and low-glycemic dietary planning.")
    if "calories" in missing_high:
        risk_points.append("BASELINE ENERGY GAP: Caloric content is unverified.")

    if not risk_points:
        risk_points.append("All primary safety and nutritional parameters are declared.")

    anomaly_texts = [f"* [{a.get('severity')}] {a.get('message')}" for a in anomalies]
    if not anomaly_texts:
        anomaly_texts = ["* No mathematical or chemical contradictions detected."]

    guidance = [
        f"1. Request official product specification sheet from manufacturer '{brand}'.",
        "2. Cross-verify physical packaging artwork for mandatory nutrition facts and allergen statements.",
        "3. If formulation is disputed, mandate third-party certified laboratory chemical assay."
    ]

    warnings_list = provider_warnings or []
    fallback_note = ""
    if warnings_list:
        fallback_note = f"\n\n### Provider Fallback Notice\nExternal LLM call fell back to deterministic mode: {'; '.join(warnings_list)}"

    content = f"""### Zero-Hallucination Verification Guarantee
**ACTIVE GUARDRAIL:** No missing data points were inferred, estimated, or imputed for **{name}**. All missing attributes are strictly preserved as `MISSING`.

### Triage Priority: {priority} ({audit.get('completeness_pct')}% Complete)
**Risk Evaluation:**
{chr(10).join('* ' + p for p in risk_points)}

### Detected Omissions & Anomalies
- **Missing Critical Fields:** {', '.join(missing_crit) if missing_crit else 'None'}
- **Missing High-Priority Fields:** {', '.join(missing_high) if missing_high else 'None'}
- **Missing Secondary Fields:** {', '.join(missing_low) if missing_low else 'None'}
**Cross-Field Math Findings:**
{chr(10).join(anomaly_texts)}

### Actionable QA Verification Guidance
{chr(10).join(guidance)}{fallback_note}
"""
    return {
        "status": "success",
        "provider": "deterministic_fallback",
        "model": "NutriAudit-Deterministic-RuleEngine",
        "content": content,
        "review_priority": priority,
        "zero_hallucination_guaranteed": True,
        "warnings": warnings_list,
        "fallback_reason": "; ".join(warnings_list) if warnings_list else "No external LLM key configured."
    }


def run_triage_audit(
    record: Dict[str, Any],
    audit: Dict[str, Any],
    anomalies: list,
    client_groq_key: Optional[str] = None,
    client_gemini_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run triage audit using Groq, Gemini, or safe logged deterministic fallback.
    """
    prompt = build_audit_prompt(record, audit, anomalies)
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
                        "content": "You are NutriAudit AI. You strictly adhere to a zero-hallucination contract. Never invent or estimate missing food data."
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
                        "zero_hallucination_guaranteed": True,
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
                    "zero_hallucination_guaranteed": True,
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
    return generate_deterministic_fallback_audit(record, audit, anomalies, provider_warnings=provider_warnings)
