#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

python3 -m avarforms.cli "$@"

echo ""
echo "Building site data..."
python3 -c "
from pathlib import Path
from avarforms.web.build_site import build_site
r = build_site()
print(f\"Site: {r['wordforms']} wordforms, {r['chunks']} chunks (build {r['build_id']})\")
"
