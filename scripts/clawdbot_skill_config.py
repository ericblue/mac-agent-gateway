#!/usr/bin/env python3
"""Configure the OpenClaw (formerly Clawdbot/Moltbot) skill entries for MAG.

This script updates ~/.clawdbot/clawdbot.json to include:

  skills.entries.mag-reminders.enabled = true
  skills.entries.mag-reminders.env.MAG_URL = <value>
  skills.entries.mag-reminders.env.MAG_API_KEY = <value>

  skills.entries.mag-messages.enabled = true
  skills.entries.mag-messages.env.MAG_URL = <value>
  skills.entries.mag-messages.env.MAG_API_KEY = <value>

It is idempotent and will create intermediate objects as needed.

Usage:
  python3 scripts/clawdbot_skill_config.py set --url http://localhost:8124 --api-key your-key
  python3 scripts/clawdbot_skill_config.py check --url http://localhost:8124

Notes:
- We do not attempt to restart OpenClaw. After editing, restart/reload the gateway if needed.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

SKILL_NAMES = ["mag-reminders", "mag-messages"]
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.clawdbot/clawdbot.json")


def _load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"OpenClaw config not found at {path}. Run `openclaw configure` first, or create the file."
        )
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at root of {path}")
    return data


def _save_json(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def _ensure_dict(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    v = parent.get(key)
    if v is None:
        v = {}
        parent[key] = v
    if not isinstance(v, dict):
        raise ValueError(f"Expected object at {key}, found {type(v).__name__}")
    return v


def cmd_set(args: argparse.Namespace) -> int:
    data = _load_json(args.path)

    skills = _ensure_dict(data, "skills")
    entries = _ensure_dict(skills, "entries")

    for skill_name in SKILL_NAMES:
        entry = _ensure_dict(entries, skill_name)
        entry["enabled"] = True
        env = _ensure_dict(entry, "env")
        env["MAG_URL"] = args.url
        env["MAG_API_KEY"] = args.api_key
        print(f"  Configured {skill_name}")

    _save_json(args.path, data)
    print(f"\nUpdated {args.path} with MAG_URL and MAG_API_KEY for all skills")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    data = _load_json(args.path)

    skills = data.get("skills", {})
    entries = skills.get("entries", {})

    all_ok = True
    for skill_name in SKILL_NAMES:
        print(f"\n{skill_name}:")
        entry = entries.get(skill_name)

        # Check if skill entry exists at all
        if entry is None:
            print("  NOT CONFIGURED (missing from clawdbot.json)")
            print(f"  Run: make clawdbot-skill-config MAG_URL={args.url} MAG_API_KEY=...")
            all_ok = False
            continue

        if not isinstance(entry, dict):
            print(f"  Invalid entry type (expected object, found {type(entry).__name__})")
            all_ok = False
            continue

        env = entry.get("env", {})
        if not isinstance(env, dict):
            print(f"  Missing or invalid 'env' section")
            all_ok = False
            continue

        url = env.get("MAG_URL")
        api_key = env.get("MAG_API_KEY")
        enabled = entry.get("enabled")

        ok = True
        if url != args.url:
            print(f"  MAG_URL: expected {args.url!r}, found {url!r}")
            ok = False

        if api_key is None:
            print("  MAG_API_KEY: missing")
            ok = False
        else:
            print("  MAG_API_KEY: set")

        if enabled is not True:
            print(f"  enabled: {enabled!r} (should be true)")
            ok = False

        if ok:
            print("  OK")
        else:
            all_ok = False

    print()
    if all_ok:
        print("All skills configured correctly")
        return 0
    else:
        print("Run 'make clawdbot-skill-config' to configure missing skills")
        return 3


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--path",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to clawdbot.json (default: {DEFAULT_CONFIG_PATH})",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("set", help="Set/overwrite MAG skill configs in clawdbot.json")
    ps.add_argument("--url", required=True, help="MAG base URL, e.g. http://localhost:8124")
    ps.add_argument("--api-key", required=True, help="MAG API key")
    ps.set_defaults(fn=cmd_set)

    pc = sub.add_parser("check", help="Check MAG skill config presence")
    pc.add_argument("--url", required=True, help="Expected MAG base URL")
    pc.set_defaults(fn=cmd_check)

    args = p.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
