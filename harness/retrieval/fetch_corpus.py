#!/usr/bin/env python3
"""Fetch the manifest corpus into a documents directory, with retries."""

from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.request
from pathlib import Path

RETRIES = 4
BACKOFF_SECONDS = 3.0
USER_AGENT = "lilbee-retrieval-sweep/1.0"


def fetch(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                dest.write_bytes(response.read())
            return
        except Exception as exc:  # noqa: BLE001 - retry loop reports at the end
            last_error = exc
            time.sleep(BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"failed after {RETRIES} attempts: {url}") from last_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(args.manifest.open(), delimiter="\t"))
    fetched = skipped = 0
    for row in rows:
        dest = args.out / row["filename"]
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            continue
        print(f"fetch {row['id']} -> {dest.name}", flush=True)
        fetch(row["url"], dest)
        fetched += 1
    print(f"corpus ready: {fetched} fetched, {skipped} already present, {len(rows)} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
