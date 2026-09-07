#!/bin/bash
# Merge the mag entry into Claude Desktop's config so Cowork sees the tools (backup kept).
# Claude Desktop launches the server over stdio and bridges it into the Cowork VM; the VM
# cannot reach MAG on the host directly, which is the whole reason this server exists.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
mkdir -p "$(dirname "$CFG")"
[ -f "$CFG" ] && cp "$CFG" "$CFG.bak.$(date +%Y%m%d%H%M%S)"
"$HERE/.venv/bin/python" - "$CFG" "$HERE" <<'PY'
import json, os, sys
cfg_path, here = sys.argv[1], sys.argv[2]
cfg = {}
if os.path.exists(cfg_path):
    with open(cfg_path) as fh:
        try: cfg = json.load(fh)
        except json.JSONDecodeError: cfg = {}
cfg.setdefault("mcpServers", {})["mag"] = {"command": f"{here}/run.sh"}
with open(cfg_path, "w") as fh:
    json.dump(cfg, fh, indent=2)
print("registered mag in", cfg_path)
print("servers now:", ", ".join(cfg["mcpServers"]))
PY
echo "Now quit and reopen the Claude desktop app."
