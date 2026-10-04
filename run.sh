#!/bin/bash
# Launch the mag-mcp stdio server. Referenced by .mcp.json / claude_desktop_config.json so
# neither has to hardcode the venv interpreter path.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# Talk to MAG directly on loopback, NOT through the local reverse proxy (https://mag.local).
# Two reasons:
#   1. This server runs on the same host as MAG. Routing loopback traffic out to Traefik in
#      Docker and back adds a hard dependency on Docker being up for no benefit.
#   2. Python does not read the macOS keychain, so the mkcert cert that `curl` accepts fails
#      here with CERTIFICATE_VERIFY_FAILED.
# Pinning also stops a MAG_URL exported in the user's shell profile from redirecting the
# server at a port or scheme it cannot use.
#
# To go through the proxy anyway, set both:
#   MAG_URL_OVERRIDE=https://mag.local
#   MAG_MCP_CA_BUNDLE="$(mkcert -CAROOT)/rootCA.pem"
export MAG_URL="${MAG_URL_OVERRIDE:-http://127.0.0.1:8123}"

export PYTHONPATH="$HERE/src"
[ -f "$HERE/.env" ] && export MAG_API_KEY="$(grep '^MAG_API_KEY=' "$HERE/.env" | cut -d= -f2- | tr -d ' ')"
exec "$HERE/.venv/bin/python" -m mag_mcp
