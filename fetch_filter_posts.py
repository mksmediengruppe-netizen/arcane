#!/usr/bin/env python3
"""
Fetch posts from jsonplaceholder.typicode.com, filter by userId, and save to JSON file.

Usage:
  python3 fetch_filter_posts.py --user-id 1 --output posts_user_1.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

import requests


def fetch_posts() -> list[dict]:
    url = "https://jsonplaceholder.typicode.com/posts"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def main():
    parser = argparse.ArgumentParser(description="Fetch and filter posts by userId")
    parser.add_argument("--user-id", type=int, default=1, help="User ID to filter by (default: 1)")
    parser.add_argument(
        "--output",
        type=str,
        default="posts_user_1.json",
        help="Output JSON filename (default: posts_user_1.json)",
    )
    args = parser.parse_args()

    try:
        posts = fetch_posts()
    except requests.RequestException as e:
        print(f"Error fetching posts: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        filtered = [p for p in posts if int(p.get("userId", -1)) == args.user_id]
    except Exception as e:  # defensive, in case of unexpected schema
        print(f"Error filtering posts: {e}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    try:
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"Error writing output file '{out_path}': {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Fetched {len(posts)} posts, filtered {len(filtered)} with userId={args.user_id}. Saved to {out_path.resolve()}"
    )


if __name__ == "__main__":
    main()
