#!/usr/bin/env bash
# Rebuild PinkiSaanp_submission.zip (manifest.json at the zip root, no variant.json / __pycache__).
set -e
cd "$(dirname "$0")/.."
python3 -m py_compile submission/PinkiSaanp/bot.py submission/PinkiSaanp/pinki/*.py
find submission -name __pycache__ -type d -prune -exec rm -rf {} +
rm -f PinkiSaanp_submission.zip
python3 - <<'EOF'
import os, zipfile
root = 'submission/PinkiSaanp'
with zipfile.ZipFile('PinkiSaanp_submission.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d != '__pycache__')
        for f in sorted(fn):
            if f == 'variant.json' or f.endswith('.pyc'):
                continue
            p = os.path.join(dp, f)
            z.write(p, os.path.relpath(p, root))
names = zipfile.ZipFile('PinkiSaanp_submission.zip').namelist()
assert 'manifest.json' in names and not any('variant' in n or 'pycache' in n for n in names)
print(names)
EOF
