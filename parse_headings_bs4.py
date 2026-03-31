#!/usr/bin/env python3
"""
Parse H1 and H2 headings from any web page.
Usage:
  python3 parse_headings_bs4.py https://example.com

- Accepts a single positional argument: URL to fetch
- Prints found H1 and H2 headings in order of appearance
"""
import argparse
import sys
from typing import List

import requests
from bs4 import BeautifulSoup


def fetch_html(url: str, timeout: int = 15, user_agent: str | None = None) -> str:
    headers = {
        "User-Agent": user_agent
        or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0 Safari/537.36 ArcaneBot/1.0"
        )
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def extract_headings(html: str) -> tuple[List[str], List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    h1_list = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h2_list = [h.get_text(strip=True) for h in soup.find_all("h2")]
    h1_list = [t for t in h1_list if t]
    h2_list = [t for t in h2_list if t]
    return h1_list, h2_list


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse H1 and H2 headings from a web page")
    parser.add_argument("url", help="Target URL to fetch, e.g., https://example.com")
    parser.add_argument("--user-agent", dest="user_agent", default=None, help="Custom User-Agent header (optional)")
    parser.add_argument("--timeout", type=int, default=15, help="Request timeout in seconds (default: 15)")
    args = parser.parse_args()

    try:
        html = fetch_html(args.url, timeout=args.timeout, user_agent=args.user_agent)
        h1_list, h2_list = extract_headings(html)

        print(f"URL: {args.url}")
        print("")
        print(f"H1 headings ({len(h1_list)}):")
        if h1_list:
            for i, t in enumerate(h1_list, 1):
                print(f"  {i}. {t}")
        else:
            print("  \u2014 none \u2014")
        print("")
        print(f"H2 headings ({len(h2_list)}):")
        if h2_list:
            for i, t in enumerate(h2_list, 1):
                print(f"  {i}. {t}")
        else:
            print("  \u2014 none \u2014")
        return 0
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
