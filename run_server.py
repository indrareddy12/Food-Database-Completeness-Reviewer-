"""
NutriAudit Backend Server Launcher (PS 134)
Run with: python run_server.py
"""

import os
import sys
from pathlib import Path

# Add backend directory to path
backend_path = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend_path))

from dotenv import load_dotenv

load_dotenv()

from backend.main import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print("=" * 70)
    print("  NUTRIAUDIT: Food Database Completeness Reviewer Server")
    print(f"  Local API & UI: http://localhost:{port}")
    print("  Default Dataset: demo_subset(1).csv (552 records)")
    print("  Zero-Hallucination Guardrail: ENFORCED")
    print("=" * 70)
    app.run(host="0.0.0.0", port=port, debug=False)
