#!/usr/bin/env python3
"""Export FastAPI OpenAPI schema to JSON without connecting to source databases (Contract C01, C08)."""

import json
from pathlib import Path
from querylens.config import Settings
from querylens.main import create_app

def export_schema():
    settings = Settings(environment="test")
    app = create_app(settings)
    openapi_schema = app.openapi()
    
    out_dir = Path(__file__).resolve().parents[1] / "packages" / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "openapi.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, sort_keys=True)
        f.write("\n")
        
    print(f"Exported OpenAPI schema to {out_file}")

if __name__ == "__main__":
    export_schema()
