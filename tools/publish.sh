#!/usr/bin/env bash
# Assemble the handoff repo contents and push to GitHub.
set -e
cd /e/Projects/Agent_Showdown
python -m py_compile submission/PinkiSaanp/bot.py submission/PinkiSaanp/pinki/*.py && echo COMPILE_OK
# baseline snapshot from WSL (if available), else from the current submission
rm -rf baselines/PinkiV1 && mkdir -p baselines
if wsl.exe -d Ubuntu -- test -d /home/lenovo/cw/my_bots/PinkiV1 2>/dev/null; then
  wsl.exe -d Ubuntu -- bash -c "cp -r ~/cw/my_bots/PinkiV1 /mnt/e/Projects/Agent_Showdown/baselines/ && rm -rf /mnt/e/Projects/Agent_Showdown/baselines/PinkiV1/pinki/__pycache__"
else
  cp -r submission/PinkiSaanp baselines/PinkiV1 && echo '{"seed": 7}' > baselines/PinkiV1/variant.json
fi
# submission zip (manifest.json at archive root)
rm -f PinkiSaanp_submission.zip
find submission -name __pycache__ -type d -exec rm -rf {} +
python - <<'EOF'
import os, zipfile
root = 'submission/PinkiSaanp'
with zipfile.ZipFile('PinkiSaanp_submission.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f == 'variant.json' or f.endswith('.pyc'):
                continue
            p = os.path.join(dp, f)
            z.write(p, os.path.relpath(p, root))
print(zipfile.ZipFile('PinkiSaanp_submission.zip').namelist())
EOF
# copy rules (README + official kit) into the repo
rm -rf Rules_repo_tmp
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
logs/
replays/
results/
References/
.claude/
tools/*.pbrp
Rules/agent-showdown-test-suite-main/out/replays/*.pbrp
Rules/agent-showdown-test-suite-main/out/logs/*.log
EOF
[ -d .git ] || git init -q
git checkout -q -B main
git add -A
git -c user.name="PinkiSaanp" -c user.email="melodybyad@gmail.com" commit -q -m "PinkiSaanp Codewars bot, baseline, rules, tools and handoff

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || true
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/LeMorpheus/PinkiSaanp.git
git push -u origin main 2>&1 | tail -5
git log --oneline | head -3
