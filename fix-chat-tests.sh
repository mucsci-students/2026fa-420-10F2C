#!/usr/bin/env bash
# Fixes two ordering mistakes in tests/test_ai_chats.py (test bugs, not app bugs). Apply once.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
sed -n '/^#__PAYLOAD_BELOW__/,$p' "$0" | tail -n +2 | tr -d '\r \t' | base64 -d | gunzip > "$work/p.patch"
if git apply --check "$work/p.patch" 2>/dev/null; then git apply "$work/p.patch"; echo "Fixed tests/test_ai_chats.py"
elif git apply --check -R "$work/p.patch" 2>/dev/null; then echo "Already applied."
else echo "tests/test_ai_chats.py is not in the expected state; nothing changed."; exit 1; fi
command -v uv >/dev/null 2>&1 && [ "${NO_TEST:-0}" != "1" ] && uv run pytest tests/test_ai_chats.py -q
exit 0
#__PAYLOAD_BELOW__
H4sIAJol4WoCA52Ub2/aMBDG3+dTnLI3RCEZWRlslSq10/5oUoUmxLsKWV5ySawGm9lmgKp+951j
KLAWyhakWNj3/Hzne5xClCUkSSUs8LcWjTXtm3HB8ppbk87X8PPIQiBkgSsoeIbDMkvTi2zIBziE
rNcb9PtBkiRHmUEcx8e519eQZP1e9wPEfqCJAktoA81S2LwWsmJqjtIwLplqCtStnP4VbmYh76Va
0opENy8rNEwq62Qdjb8WaAJwvycq8rz2hJobJqxhTj7DmdJrVirNbI2U40ZsWXQZxECPz1ljrnTR
MWiMUHIX1IVwYVCHNFImYQTwBtqsgXBQCm1sSwgcCp7JUzqUWhhLOcAV3D2EWjUYXu6guZIWpXVT
jv84DZJ/T8pv7pO52miN5RafS6O7kOdW/MZw6lU+WuKyPbsXBD6MG9rQvlIgVTh1B8SBeC0ZKA1t
DVDHa5AKfDu8Pd6/a+1Bw8cDe/xHIw+dwNm2HEbR3m1OWKF1Zlu3JiIKrS9phyUX1k04NGdrNPvk
thsTpZpParVXdc6bphMW2KBFppWaUS8eQslnbXPHqijWkF0MwsfokPCV3+PYU55o6eZQoy12rnHO
NTKT11gsGmQVStTcUgz1Oj6V0Umpa03HR1C9UGg1N9SrTf3gq+mCUeRtYaBSaLyp/tr0rCLOOpt4
z1rUHW6tfsntuyJS9uP2ZsRuJpNxBJQjfRFgRHfgwKQnSJsvCWG+jD5/H307Rjr7/q22t+/1e/QH
/PNCcakFAAA=