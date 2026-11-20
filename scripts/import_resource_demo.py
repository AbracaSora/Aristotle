"""Load 408 resource fixtures into the existing learning UI, preserving history."""

import argparse
import json

from aristotle_backend.config import database_url
from aristotle_backend.db import open_database
from aristotle_backend.resource_seed import import_resource_demo

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", required=True)
    parser.parse_args()
    engine, sessions = open_database(database_url())
    try:
        print(json.dumps(import_resource_demo(sessions), ensure_ascii=False))
    finally:
        engine.dispose()
