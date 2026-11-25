"""Embed audited food database records and store/query them in Pinecone.

Enforces the Zero-Hallucination Constraint:
- Runs Stage 1 deterministic audit (csv_auditor.py) before embedding.
- Never invents missing ingredients, allergens, or nutrient values.
- Stores audit flags (`audit_priority`, `missing_fields`, `invalid_fields`,
  `is_verified_safe`) inside Pinecone metadata so retrieval can filter out
  unsafe or corrupted records.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from csv_auditor import (
    TIER_2_NUTRITION,
    CsvAuditRecord,
    audit_csv_row,
    clean_str,
    parse_clean_float,
)


def build_embedding_text(row: dict[str, Any], audit: CsvAuditRecord) -> str:
    """Create a clean, factual text document for embedding without inventing data."""
    parts: list[str] = []

    name = html.unescape(audit.product_name) if audit.product_name else "UNVERIFIED PRODUCT NAME"
    brand = html.unescape(audit.brands) if audit.brands else "Unknown Brand"
    categories = clean_str(row.get("categories"))
    serving = clean_str(row.get("serving_size"))
    ingredients = clean_str(row.get("ingredients_text"))
    allergens = clean_str(row.get("allergens"))

    parts.append(f"Product: {name}")
    parts.append(f"Brand: {brand}")
    if categories:
        parts.append(f"Categories: {html.unescape(categories)}")
    if serving:
        parts.append(f"Serving Size: {html.unescape(serving)}")

    if ingredients:
        parts.append(f"Ingredients: {html.unescape(ingredients)}")
    else:
        parts.append("Ingredients: MISSING (Unverified)")

    if allergens:
        parts.append(f"Declared Allergens: {html.unescape(allergens)}")
    else:
        parts.append("Declared Allergens: MISSING (Unverified)")

    # Include only verified, non-invalid nutrition values
    valid_nutrients: list[str] = []
    for col in TIER_2_NUTRITION:
        if col in audit.invalid_fields:
            continue
        num, err = parse_clean_float(row.get(col))
        if err is None and num is not None:
            valid_nutrients.append(f"{col}={num}")
    if valid_nutrients:
        parts.append("Nutrition per 100g: " + ", ".join(valid_nutrients))
    else:
        parts.append("Nutrition per 100g: MISSING")

    parts.append(f"Audit Priority: {audit.baseline_priority}")
    return " | ".join(parts)


def build_pinecone_metadata(
    row: dict[str, Any], audit: CsvAuditRecord, text: str
) -> dict[str, Any]:
    """Build flat Pinecone-compatible metadata (strings, numbers, booleans, list[str])."""
    allergens = clean_str(row.get("allergens"))
    ingredients = clean_str(row.get("ingredients_text"))
    categories = clean_str(row.get("categories"))
    image_url = clean_str(row.get("image_url"))

    has_missing_critical = (allergens is None) or (ingredients is None) or any(
        f in ("allergens", "ingredients_text") for f in audit.invalid_fields
    )
    completeness_score = float(audit.nutrition_completeness_pct or 0.0)

    meta: dict[str, Any] = {
        "code": audit.code,
        "product_name": html.unescape(audit.product_name) if audit.product_name else "",
        "brands": html.unescape(audit.brands) if audit.brands else "",
        "categories": html.unescape(categories) if categories else "",
        "allergens": html.unescape(allergens) if allergens else "",
        "has_allergens": allergens is not None,
        "has_ingredients": ingredients is not None,
        "has_missing_critical": has_missing_critical,
        "review_priority": audit.baseline_priority,
        "audit_priority": audit.baseline_priority,
        "completeness_score": completeness_score,
        "needs_llm_review": audit.needs_llm_review,
        "is_verified_safe": audit.baseline_priority in ("NONE", "LOW"),
        "missing_fields": audit.missing_fields,
        "invalid_fields": audit.invalid_fields,
        "nutrition_completeness_pct": completeness_score,
        "text": text[:3500],  # Stay well within Pinecone 40KB metadata limit
    }
    if image_url:
        meta["image_url"] = image_url

    # Store verified numeric nutrition fields for metadata filtering (skip invalid/missing)
    for col in ("energy_kcal_100g", "proteins_100g", "sugars_100g", "sodium_100g", "fiber_100g"):
        if col in audit.invalid_fields:
            continue
        num, err = parse_clean_float(row.get(col))
        if err is None and num is not None:
            meta[col] = num

    return meta


def prepare_documents(csv_path: Path, deduplicate: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load CSV, run Stage 1 audit, deduplicate by code, and prepare vector payloads."""
    df = pd.read_csv(csv_path, dtype={"code": str})
    raw_rows = df.to_dict(orient="records")

    prepared: list[dict[str, Any]] = []
    seen_codes: dict[str, dict[str, Any]] = {}
    duplicate_count = 0

    for idx, row in enumerate(raw_rows):
        audit = audit_csv_row(idx, row)
        text = build_embedding_text(row, audit)
        metadata = build_pinecone_metadata(row, audit, text)
        doc = {
            "id": audit.code,
            "text": text,
            "metadata": metadata,
            "audit": audit,
        }

        if deduplicate:
            if audit.code in seen_codes:
                duplicate_count += 1
                # Keep the record with fewer total issues (higher quality)
                prev_issues = len(seen_codes[audit.code]["audit"].missing_fields) + len(
                    seen_codes[audit.code]["audit"].invalid_fields
                )
                curr_issues = len(audit.missing_fields) + len(audit.invalid_fields)
                if curr_issues < prev_issues:
                    seen_codes[audit.code] = doc
            else:
                seen_codes[audit.code] = doc
        else:
            doc["id"] = f"{audit.code}#{idx}"
            prepared.append(doc)

    if deduplicate:
        prepared = list(seen_codes.values())

    stats = {
        "source_csv": str(csv_path),
        "raw_rows": len(raw_rows),
        "duplicates_collapsed": duplicate_count,
        "unique_vectors_ready": len(prepared),
        "verified_safe_vectors": sum(1 for d in prepared if d["metadata"]["is_verified_safe"]),
        "high_priority_flagged": sum(
            1 for d in prepared if d["metadata"]["audit_priority"] == "HIGH"
        ),
    }
    return prepared, stats


def ensure_pinecone_index(pc: Any, index_name: str, dimension: int, cloud: str, region: str) -> Any:
    """Create serverless Pinecone index if missing and return Index handle."""
    from pinecone import ServerlessSpec

    existing = {idx.name for idx in pc.list_indexes()}
    if index_name not in existing:
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud=cloud, region=region),
        )
    return pc.Index(index_name)


def embed_texts_pinecone(pc: Any, texts: list[str], model: str, input_type: str = "passage") -> list[list[float]]:
    """Generate embeddings using Pinecone Inference API in batches."""
    vectors: list[list[float]] = []
    batch_size = 96
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = pc.inference.embed(
            model=model,
            inputs=batch,
            parameters={"input_type": input_type, "truncate": "END"},
        )
        vectors.extend([item["values"] for item in resp.data])
    return vectors


def upsert_to_pinecone(
    docs: list[dict[str, Any]],
    index_name: str,
    namespace: str,
    embed_model: str,
    cloud: str,
    region: str,
) -> None:
    """Embed prepared documents and upsert them into Pinecone."""
    from pinecone import Pinecone

    api_key = os.environ.get("PINECONE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "PINECONE_API_KEY is not set. Add it to .env or export it in your terminal."
        )

    if not docs:
        print(json.dumps({"status": "SKIPPED", "message": "No valid documents to upsert."}, indent=2))
        return

    pc = Pinecone(api_key=api_key)
    texts = [d["text"] for d in docs]
    embeddings = embed_texts_pinecone(pc, texts, model=embed_model, input_type="passage")
    dimension = len(embeddings[0])

    index = ensure_pinecone_index(pc, index_name, dimension=dimension, cloud=cloud, region=region)

    batch_size = 100
    for i in range(0, len(docs), batch_size):
        batch_docs = docs[i : i + batch_size]
        batch_embs = embeddings[i : i + batch_size]
        vectors = [
            {
                "id": doc["id"],
                "values": emb,
                "metadata": doc["metadata"],
            }
            for doc, emb in zip(batch_docs, batch_embs)
        ]
        index.upsert(vectors=vectors, namespace=namespace)

    print(
        json.dumps(
            {
                "status": "SUCCESS",
                "index_name": index_name,
                "namespace": namespace,
                "embed_model": embed_model,
                "dimension": dimension,
                "vectors_upserted": len(docs),
            },
            indent=2,
        )
    )


def query_pinecone(
    query_text: str,
    index_name: str,
    namespace: str,
    embed_model: str,
    top_k: int,
    safe_only: bool,
) -> None:
    """Query Pinecone using semantic similarity + optional safety metadata filter."""
    from pinecone import Pinecone

    api_key = os.environ.get("PINECONE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PINECONE_API_KEY is not set.")

    pc = Pinecone(api_key=api_key)
    q_emb = embed_texts_pinecone(pc, [query_text], model=embed_model, input_type="query")[0]
    index = pc.Index(index_name)

    meta_filter = {"is_verified_safe": {"$eq": True}} if safe_only else None
    res = index.query(
        namespace=namespace,
        vector=q_emb,
        top_k=top_k,
        include_metadata=True,
        filter=meta_filter,
    )

    matches = [
        {
            "id": m["id"],
            "score": round(float(m["score"]), 4),
            "product_name": m["metadata"].get("product_name"),
            "brands": m["metadata"].get("brands"),
            "audit_priority": m["metadata"].get("audit_priority"),
            "missing_fields": m["metadata"].get("missing_fields"),
            "invalid_fields": m["metadata"].get("invalid_fields"),
            "proteins_100g": m["metadata"].get("proteins_100g"),
        }
        for m in res.get("matches", [])
    ]
    print(json.dumps({"query": query_text, "safe_only": safe_only, "matches": matches}, indent=2, ensure_ascii=False))


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser = argparse.ArgumentParser(description="Audit, embed, and store food DB in Pinecone.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parent / "demo_subset.csv",
        help="Path to food CSV file.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Prepare & preview payloads without calling Pinecone.")
    parser.add_argument("--upsert", action="store_true", help="Embed and upsert records to Pinecone.")
    parser.add_argument("--query", type=str, default=None, help="Run a semantic search query against Pinecone.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of search results.")
    parser.add_argument("--safe-only", action="store_true", help="Filter out HIGH/MEDIUM priority unverified items.")
    parser.add_argument(
        "--index",
        type=str,
        default=os.environ.get("PINECONE_INDEX")
        or os.environ.get("PINECONE_INDEX_NAME")
        or "food-database-completeness",
    )
    parser.add_argument("--namespace", type=str, default="food-products")
    parser.add_argument("--model", type=str, default=os.environ.get("PINECONE_EMBED_MODEL", "multilingual-e5-large"))
    parser.add_argument("--cloud", type=str, default=os.environ.get("PINECONE_CLOUD", "aws"))
    parser.add_argument(
        "--region",
        type=str,
        default=os.environ.get("PINECONE_ENVIRONMENT")
        or os.environ.get("PINECONE_REGION")
        or "us-east-1",
    )
    args = parser.parse_args()

    if args.query:
        query_pinecone(
            query_text=args.query,
            index_name=args.index,
            namespace=args.namespace,
            embed_model=args.model,
            top_k=args.top_k,
            safe_only=args.safe_only,
        )
        return

    docs, stats = prepare_documents(args.input)

    if args.dry_run or not args.upsert:
        sample_payloads = [
            {
                "id": d["id"],
                "text_preview": d["text"],
                "metadata": d["metadata"],
            }
            for d in docs[:3]
        ]
        print(
            json.dumps(
                {
                    "mode": "DRY_RUN",
                    "stats": stats,
                    "sample_vector_payloads": sample_payloads,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    upsert_to_pinecone(
        docs=docs,
        index_name=args.index,
        namespace=args.namespace,
        embed_model=args.model,
        cloud=args.cloud,
        region=args.region,
    )


if __name__ == "__main__":
    main()
