"""Material-import worker. Run separately from model workers; no external model calls."""

import argparse
import time

from .config import database_url
from .db import open_database
from .import_jobs import expire_imports, run_import


def main():
    from .runtime_logging import configure_logging

    configure_logging("import_worker")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine, sessions = open_database(database_url())
    try:
        while True:
            expire_imports(sessions)
            result = run_import(sessions)
            if args.once:
                return
            if result is None:
                time.sleep(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
