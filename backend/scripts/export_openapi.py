"""Export the API contract for the frontend (15.6). Run it every time the API changes:

    uv run python -m scripts.export_openapi [output_dir]

Writes openapi.json and error_codes.json (table 14.2) to the frontend repository,
by default the sibling folder ../fe-looply/.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT.parent / "fe-looply"

# Importing the app needs these settings, but exporting never touches the database.
for key, value in {
    "DATABASE_URL": "postgresql://unused@localhost/unused",
    "DEFAULT_BUSINESS_SLUG": "unused",
    "PRIVACY_POLICY_VERSION": "unused",
}.items():
    os.environ.setdefault(key, value)

from app.core.errors import ERROR_CATALOG
from app.main import app


def export(output_dir: Path) -> list[Path]:
    if not output_dir.is_dir():
        raise SystemExit(f"Output folder does not exist: {output_dir}")
    openapi = output_dir / "openapi.json"
    openapi.write_text(
        json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    errors = output_dir / "error_codes.json"
    errors.write_text(
        json.dumps(
            {
                code: {"status": status, "message": message}
                for code, (status, message) in ERROR_CATALOG.items()
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return [openapi, errors]


def main() -> None:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT_DIR
    for path in export(output_dir):
        print(f"Written: {path}")


if __name__ == "__main__":
    main()
