#!/usr/bin/env bash
# Small fix to gui/ai/undo.py: asking to undo a change that is already undone (with nothing else left to
# undo) now says "already undone" instead of "nothing to undo". Apply once; safe to run twice.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
sed -n '/^#__PAYLOAD_BELOW__/,$p' "$0" | tail -n +2 | tr -d '\r \t' | base64 -d | gunzip > "$work/p.patch"
if git apply --check "$work/p.patch" 2>/dev/null; then git apply "$work/p.patch"; echo "Fixed gui/ai/undo.py"
elif git apply --check -R "$work/p.patch" 2>/dev/null; then echo "Already applied."
else echo "gui/ai/undo.py is not in the expected state; nothing changed."; exit 1; fi
command -v uv >/dev/null 2>&1 && [ "${NO_TEST:-0}" != "1" ] && uv run pytest tests/test_ai_smarter.py -q
exit 0
#__PAYLOAD_BELOW__
H4sIABor4WoCA51TS4/TMBC+51eMcmmsNOlD2wUqFS1CHLjAgeVUVpGTTBqL1C62q2612v/O2HFL
t91FC7lEceZ7zDfjWjQNZNlKWOCj1VaMuBhtZa3yzR7Ks4NIyBrv4e0bfj2dzvJ8PCv5VTODyXh8
fXUVZVl2wRGlaXrJc3MD2bvZcDqG1L0mQAc1NmBatSuqlssVFq0wVul9ovHXFo0dAtcrM4cv6gO9
GWTvwVg9jzzO8QacOQd8p39HyNetrdQaCeYeY7lFWECQKiolrVZdhzqv0VRalBc2WI9EKhRoCOs5
lrF3EE7juyhzRaIBqeyhdt4fukdzYRA+HtU+aa10Et+2qBGEcahWyBVY5TvLYxZlPdpY3DjVtZCJ
ay+v1FZSqx3KJOiwYHHHpcWaag+F0nIhHa3SEMcsp/jEJmFR+o/E1FbPHVJ0T0vrswCJ9zZJtNpB
QxruLeQxKoIVa26r1o1I7YaBhLEhzVQi+0NGlY6PgnA/TlTCTy73ybNUp7JhLhpP58LOyF4exuC2
5Rb6lXJOeKeR13s/D4k5fON78OSxm1KpXa7kueTVz3wQMj2x/GQP0tdZ+Os+vAJ/2WoTfwaaa1fL
gYWGLjPwQ4s+TqcxeOjDfBzkQAZopjta+1BGOWic/5APhcaK+jmsxhBm7DF+Knji8bBcNNVl7D/o
ivgUsHsxnP8JpZfseImd01s+c7Fd7fEy+4Up3Lpo117ivbG7454H4wuYzKPfjl5KQikFAAA=