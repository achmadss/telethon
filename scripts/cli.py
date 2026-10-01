#!/usr/bin/env python3
"""Small orchestrator CLI that talks to the mimic-telethon HTTP API.

Examples:
    python scripts/cli.py health
    python scripts/cli.py send --to @my_bot --message "hello from the agent"
    python scripts/cli.py read --peer @my_bot --limit 5
"""
import argparse
import json
import os

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="mimic-telethon API client")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MIMIC_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("MIMIC_API_TOKEN", ""),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")

    send = sub.add_parser("send")
    send.add_argument("--to", required=True, help="@username, phone, or id")
    send.add_argument("--message", required=True)

    read = sub.add_parser("read")
    read.add_argument("--peer", required=True)
    read.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    with httpx.Client(base_url=args.base_url, headers=headers, timeout=30) as http:
        if args.command == "health":
            resp = http.get("/health")
        elif args.command == "send":
            resp = http.post("/send", json={"to": args.to, "message": args.message})
        elif args.command == "read":
            resp = http.get(f"/messages/{args.peer}", params={"limit": args.limit})
        else:  # pragma: no cover
            parser.error("unknown command")

    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    resp.raise_for_status()


if __name__ == "__main__":
    main()
