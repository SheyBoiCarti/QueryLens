#!/usr/bin/env python3
"""Export FastAPI OpenAPI schema to JSON without connecting to source databases (Contract C01, C08)."""

import json
import sys
from pathlib import Path
from querylens.config import Settings, set_settings


def export_schema(check: bool = False) -> int:
    settings = Settings(_env_file=None, environment="test")
    set_settings(settings)
    from querylens.main import create_app

    app = create_app(settings)
    openapi_schema = app.openapi()

    out_dir = Path(__file__).resolve().parents[1] / "packages" / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "openapi.json"

    formatted = json.dumps(openapi_schema, indent=2, sort_keys=True) + "\n"

    if check:
        if not out_file.exists():
            print(f"Error: {out_file} does not exist. Run export_schema.py to generate it.", file=sys.stderr)
            return 1
        with open(out_file, "r", encoding="utf-8") as f:
            existing = f.read()
        if existing != formatted:
            print(f"Error: OpenAPI schema drifted from live FastAPI spec in {out_file}.", file=sys.stderr)
            return 1
        print(f"OpenAPI schema matches live spec ({out_file}).")
        return 0

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(formatted)

    print(f"Exported OpenAPI schema to {out_file}")
    return 0


if __name__ == "__main__":
    check_mode = "--check" in sys.argv
    sys.exit(export_schema(check=check_mode))
