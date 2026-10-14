"""(Re)create the sample business database.

Usage (from the backend/ directory):
    python -m scripts.seed_database            # create data/business.db if missing
    python -m scripts.seed_database --force    # rebuild it from scratch
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.db.database import sqlite_path_from_url
from app.db.seed import build_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing database")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    args = parser.parse_args()

    path = sqlite_path_from_url(get_settings().database_url)
    if path.exists() and not args.force:
        print(f"Database already exists at {path} (use --force to rebuild).")
        return
    counts = build_database(path, seed=args.seed)
    print(f"Created {path}")
    for table, count in counts.items():
        print(f"  {table:<12} {count:>6} rows")


if __name__ == "__main__":
    main()
