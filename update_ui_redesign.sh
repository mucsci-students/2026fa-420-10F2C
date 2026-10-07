#!/usr/bin/env bash
#
# update_ui_redesign.sh -- brings an EXISTING ui/layout-redesign branch (the one that
# already has the redesign committed) up to date with the newest develop.
#
# Use this when your branch already contains the redesign and develop has moved on
# (here: the loading-state and dark-mode pull requests, #92 and #93).
# For a branch that does NOT have the redesign yet, use apply_ui_redesign.sh instead.
#
# WHAT IT DOES
#   1. fetches origin/develop and switches to the branch
#   2. merges origin/develop into it, without committing yet (a normal merge, so
#      your earlier commits and any teammates' commits stay as they are)
#   3. settles the one expected overlap (config_editor.html: keeps the redesigned
#      page) and applies a small follow-up patch that
#        * keeps the loading-state attributes on the redesigned forms
#        * adds dark-mode colours for the redesigned pages
#        * removes a duplicated stylesheet link in base.html
#   4. leaves everything uncommitted for you to test, then commit
#
# USAGE
#   bash update_ui_redesign.sh                  run from anywhere inside your clone
#   bash update_ui_redesign.sh --branch NAME    use a different branch name
#
# UNDO (before you commit)
#   git merge --abort        (or, if the merge step had nothing to do: git checkout -- gui)
#
# SAFETY
#   * refuses to run with uncommitted changes to tracked files
#   * if anything unexpected happens (other conflicts, patch does not fit) it aborts
#     the merge and leaves your branch exactly as it was
#   * the embedded patch is checked against a SHA-256 checksum before use
#
set -euo pipefail

PATCH_SHA256="36f0b197af0dd96669e86cfe25cec1aef0db7d383ca91a812cfcbc714f03ac4a"
BRANCH="ui/layout-redesign"

info() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --branch)
            [ $# -ge 2 ] || die "--branch needs a branch name"
            BRANCH="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d' ' -f1
    else
        echo "unavailable"
    fi
}

command -v git >/dev/null 2>&1 || die "git is not installed"
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this from inside your clone of the project"
cd "$ROOT"
[ -f gui/templates/gui/base.html ] || die "this does not look like the scheduler project"
git remote get-url origin >/dev/null 2>&1 || die "this clone has no 'origin' remote"
git rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null || die "there is no local branch '$BRANCH'. (To put the redesign on a fresh branch use apply_ui_redesign.sh.)"

if ! git diff --quiet HEAD -- 2>/dev/null; then
    die "you have uncommitted changes to tracked files. Commit or stash them first, then run this again."
fi

PATCH_FILE=$(mktemp "${TMPDIR:-/tmp}/ui-update.XXXXXX")
ERR_FILE=$(mktemp "${TMPDIR:-/tmp}/ui-update-err.XXXXXX")
trap 'rm -f "$PATCH_FILE" "$ERR_FILE"' EXIT

sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | sed '1d' | base64 --decode > "$PATCH_FILE" 2>/dev/null \
    || die "could not decode the embedded patch (was this file edited or re-saved?)"
ACTUAL_SHA=$(sha256_of "$PATCH_FILE")
if [ "$ACTUAL_SHA" = "unavailable" ]; then
    warn "no sha256sum/shasum found; skipping the checksum check"
elif [ "$ACTUAL_SHA" != "$PATCH_SHA256" ]; then
    die "the embedded patch is corrupted (checksum mismatch). Download the script again."
fi

START_REF=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || git rev-parse HEAD)
info "Fetching the latest develop from origin..."
git fetch origin develop || die "could not fetch origin/develop (are you online?)"
[ "$START_REF" = "$BRANCH" ] || git checkout -q "$BRANCH"

MERGING=0
bail() {
    # put the branch back exactly as it was, then explain
    if [ "$MERGING" -eq 1 ]; then git merge --abort 2>/dev/null || true; fi
    [ "$START_REF" = "$BRANCH" ] || git checkout -q "$START_REF" 2>/dev/null || true
    die "$1"
}

if git merge-base --is-ancestor origin/develop HEAD; then
    info "'$BRANCH' already contains the latest develop; no merge needed."
else
    info "Merging origin/develop into '$BRANCH' (not committed yet)..."
    MERGING=1
    git merge --no-commit --no-ff origin/develop >/dev/null 2>&1 || true
    CONFLICTS=$(git diff --name-only --diff-filter=U)
    for f in $CONFLICTS; do
        case "$f" in
            gui/templates/gui/config_editor.html)
                info "Keeping the redesigned $f"
                git checkout --ours -- "$f"
                git add -- "$f" ;;
            *) bail "unexpected merge conflict in $f. Nothing was changed. Ask for an updated script." ;;
        esac
    done
fi

if ! git apply --check "$PATCH_FILE" 2> "$ERR_FILE"; then
    cat "$ERR_FILE" >&2
    bail "the follow-up patch does not fit your branch (it expects the redesign exactly as it was first
       applied, plus develop), so nothing was changed. Ask for an updated script."
fi
git apply "$PATCH_FILE"

info "Done. Changes waiting for you (not committed):"
git status --short

cat <<'NEXT'

Next steps
  1. Start the app:      uv run python manage.py runserver
     (hard-refresh the page, Ctrl/Cmd+Shift+R)
  2. Run the tests:      uv run pytest
  3. Check both themes (Dark mode button in the top bar) and the pages that have
     loading states: Load / Save / Validate configuration, Load / Export schedules.
  4. Happy with it?      git add -A gui && git commit      (finishes the merge)
                         git push
     Not happy?          see UNDO at the top of this script
NEXT
exit 0
__PAYLOAD_BELOW__
ZGlmZiAtLWdpdCBhL2d1aS9zdGF0aWMvZ3VpL2Nzcy9zdHlsZS5jc3MgYi9ndWkvc3RhdGljL2d1
aS9jc3Mvc3R5bGUuY3NzCmluZGV4IDJkN2ZkOGQuLmY1ZmVjMTcgMTAwNjQ0Ci0tLSBhL2d1aS9z
dGF0aWMvZ3VpL2Nzcy9zdHlsZS5jc3MKKysrIGIvZ3VpL3N0YXRpYy9ndWkvY3NzL3N0eWxlLmNz
cwpAQCAtMTM0NSwzICsxMzQ1LDYwIEBAIGh0bWxbZGF0YS10aGVtZT0iZGFyayJdIC53ZWVrLWdy
aWRfX2hvdXIgeyBjb2xvcjogI2ExYTFhYTsgfQogCiAvKiBMb2FkaW5nIHNwaW5uZXIgKi8KIGh0
bWxbZGF0YS10aGVtZT0iZGFyayJdIC5zcGlubmVyIHsgYm9yZGVyLWNvbG9yOiAjMWUzYThhOyBi
b3JkZXItdG9wLWNvbG9yOiAjOTNjNWZkOyB9CisKKy8qIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLSAqCisgKiBEYXJrIG1v
ZGUgZm9yIHRoZSBsYXlvdXQgcmVkZXNpZ24gKGNhcmRzLCBzaWRlYmFyLCBjaGlwcywgcGFuZWxz
KS4gICoKKyAqIFRoZSBydWxlcyBhYm92ZSBjb3ZlciB0aGUgb2xkZXIgY2xhc3NlczsgdGhpcyBi
bG9jayByZS1jb2xvdXJzIHRoZSAqCisgKiBkZXNpZ24gdG9rZW5zIGFuZCB0aGUgZmV3IGNvbG91
cnMgdGhlIGxheW91dCBoYXJkLWNvZGVzLiAgICAgICAgICAgICoKKyAqIC0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLSAqLwor
aHRtbFtkYXRhLXRoZW1lPSJkYXJrIl0geworICAgIC0tYmc6ICMwYjBiMGM7CisgICAgLS1zdXJm
YWNlOiAjMTQxNDE2OworICAgIC0tc3VyZmFjZS1hbHQ6ICMxYzFjMWY7CisgICAgLS1ib3JkZXI6
ICMyNzI3MmE7CisgICAgLS1ib3JkZXItc3Ryb25nOiAjM2YzZjQ2OworICAgIC0tdGV4dDogI2Yz
ZjRmNjsKKyAgICAtLW11dGVkOiAjYTFhMWFhOworICAgIC0taGVhZGVyLWJnOiAjMDAwOworICAg
IC0taGVhZGVyLXRleHQ6ICNkMWQ1ZGI7CisgICAgLS1hY2NlbnQ6ICM2MGE1ZmE7CisgICAgLS1h
Y2NlbnQtc3Ryb25nOiAjOTNjNWZkOworICAgIC0tYWNjZW50LXNvZnQ6ICMxNzI1NTQ7CisgICAg
LS1mb2N1czogIzYwYTVmYTsKKyAgICAtLWRhbmdlcjogI2Y4NzE3MTsKKyAgICAtLWRhbmdlci1z
b2Z0OiAjNDUwYTBhOworICAgIC0tb2s6ICMyMmM1NWU7CisgICAgLS1vay1zb2Z0OiAjMDUyZTE2
OworICAgIC0td2FybjogI2Y1OWUwYjsKKyAgICAtLXdhcm4tc29mdDogIzQ1MWEwMzsKKyAgICAt
LXdhcm4tdGV4dDogI2ZkZTY4YTsKKyAgICAtLXNoYWRvdzogMCAxcHggMnB4IHJnYmEoMCwgMCwg
MCwgMC41KTsKKyAgICAtLXNoYWRvdy1ob3ZlcjogMCA0cHggMTRweCByZ2JhKDAsIDAsIDAsIDAu
Nik7Cit9CisKKy8qIExpbmtzIHRoYXQgYWN0IGFzIGNhcmRzIG9yIG1lbnUgaXRlbXMga2VlcCB0
aGVpciBvd24gY29sb3VycworICAgKHRoZSBnZW5lcmFsICJtYWluIGEiIGNvbG91ciBhYm92ZSBp
cyBmb3IgcGxhaW4gdGV4dCBsaW5rcykuICovCitodG1sW2RhdGEtdGhlbWU9ImRhcmsiXSBtYWlu
IC5jb25maWctc2lkZWJhciBhIHsgY29sb3I6IHZhcigtLXRleHQpOyB9CitodG1sW2RhdGEtdGhl
bWU9ImRhcmsiXSBtYWluIC5jb25maWctc2lkZWJhciBhLmlzLWFjdGl2ZSB7IGNvbG9yOiB2YXIo
LS1hY2NlbnQtc3Ryb25nKTsgfQoraHRtbFtkYXRhLXRoZW1lPSJkYXJrIl0gbWFpbiBhLmFyZWEt
Y2FyZCwKK2h0bWxbZGF0YS10aGVtZT0iZGFyayJdIG1haW4gYS5tb2RlLWNhcmQgeyBjb2xvcjog
dmFyKC0tdGV4dCk7IH0KKworLyogU2F2ZWQvdW5zYXZlZCBwaWxsOiBrZWVwIHRoZSBhbWJlciBw
aWxsIHJlYWRhYmxlIG9uIHRoZSBibGFjayBoZWFkZXIuICovCitodG1sW2RhdGEtdGhlbWU9ImRh
cmsiXSBuYXYgLm5hdi1zdGF0dXMtLWRpcnR5IHsgY29sb3I6ICM0NTFhMDM7IH0KK2h0bWxbZGF0
YS10aGVtZT0iZGFyayJdIG5hdiAubmF2LXN0YXR1cy0tZGlydHkgc3Ryb25nIHsgY29sb3I6ICM0
NTFhMDM7IH0KKworaHRtbFtkYXRhLXRoZW1lPSJkYXJrIl0gLmNoaXAgeyBiYWNrZ3JvdW5kOiAj
MjcyNzJhOyBib3JkZXItY29sb3I6ICMzZjNmNDY7IGNvbG9yOiAjZTRlNGU3OyB9CitodG1sW2Rh
dGEtdGhlbWU9ImRhcmsiXSAuY2hpcC0taW5mbyB7IGJhY2tncm91bmQ6ICMxNzI1NTQ7IGJvcmRl
ci1jb2xvcjogIzFlM2E4YTsgY29sb3I6ICNiZmRiZmU7IH0KK2h0bWxbZGF0YS10aGVtZT0iZGFy
ayJdIC5jaGlwLS1vayAgIHsgYmFja2dyb3VuZDogIzA1MmUxNjsgYm9yZGVyLWNvbG9yOiAjMTY2
NTM0OyBjb2xvcjogI2JiZjdkMDsgfQoraHRtbFtkYXRhLXRoZW1lPSJkYXJrIl0gLmNoaXAtLW9m
ZiAgeyBiYWNrZ3JvdW5kOiAjMTgxODFiOyBib3JkZXItY29sb3I6ICMzZjNmNDY7IGNvbG9yOiAj
YTFhMWFhOyB9CitodG1sW2RhdGEtdGhlbWU9ImRhcmsiXSAuY2hpcC0td2FybiB7IGJhY2tncm91
bmQ6ICM0NTFhMDM7IGJvcmRlci1jb2xvcjogIzkyNDAwZTsgY29sb3I6ICNmZGU2OGE7IH0KKwor
aHRtbFtkYXRhLXRoZW1lPSJkYXJrIl0gLmFkZC1wYW5lbCA+IHN1bW1hcnk6OmJlZm9yZSB7IGJh
Y2tncm91bmQ6ICMyNTYzZWI7IGNvbG9yOiAjZmZmOyB9CitodG1sW2RhdGEtdGhlbWU9ImRhcmsi
XSAuZm9ybS1hY3Rpb25zIHsgYm94LXNoYWRvdzogMCAtNHB4IDEycHggcmdiYSgwLCAwLCAwLCAw
LjUpOyB9CitodG1sW2RhdGEtdGhlbWU9ImRhcmsiXSAuZmllbGQgaW5wdXQsCitodG1sW2RhdGEt
dGhlbWU9ImRhcmsiXSAuZmllbGQgc2VsZWN0IHsgYmFja2dyb3VuZDogIzE4MTgxYjsgYm9yZGVy
LWNvbG9yOiAjNTI1MjViOyB9CitodG1sW2RhdGEtdGhlbWU9ImRhcmsiXSAuZmllbGQtZXJyb3Ig
eyBjb2xvcjogI2ZjYTVhNTsgfQoraHRtbFtkYXRhLXRoZW1lPSJkYXJrIl0gLmVtcHR5LXN0YXRl
IHsgYm9yZGVyLWNvbG9yOiAjNTI1MjViOyB9CitodG1sW2RhdGEtdGhlbWU9ImRhcmsiXSAuZGF0
YS10YWJsZSB0aCB7IGJhY2tncm91bmQ6IHZhcigtLXN1cmZhY2UtYWx0KTsgfQoraHRtbFtkYXRh
LXRoZW1lPSJkYXJrIl0gLmJhZGdlIHsgY29sb3I6ICM0NTFhMDM7IH0KK2h0bWxbZGF0YS10aGVt
ZT0iZGFyayJdIC5saXN0LXRvb2xiYXIgaW5wdXQgeyBiYWNrZ3JvdW5kOiAjMTgxODFiOyBjb2xv
cjogI2YzZjRmNjsgYm9yZGVyLWNvbG9yOiAjNTI1MjViOyB9CmRpZmYgLS1naXQgYS9ndWkvdGVt
cGxhdGVzL2d1aS9iYXNlLmh0bWwgYi9ndWkvdGVtcGxhdGVzL2d1aS9iYXNlLmh0bWwKaW5kZXgg
YjNiNjA2MS4uNzMzYjgwNiAxMDA2NDQKLS0tIGEvZ3VpL3RlbXBsYXRlcy9ndWkvYmFzZS5odG1s
CisrKyBiL2d1aS90ZW1wbGF0ZXMvZ3VpL2Jhc2UuaHRtbApAQCAtNiw3ICs2LDYgQEAKICAgICA8
bWV0YSBuYW1lPSJ2aWV3cG9ydCIgY29udGVudD0id2lkdGg9ZGV2aWNlLXdpZHRoLCBpbml0aWFs
LXNjYWxlPTEiPgogICAgIDx0aXRsZT57JSBibG9jayB0aXRsZSAlfVNjaGVkdWxlcnslIGVuZGJs
b2NrICV9PC90aXRsZT4KICAgICA8bGluayByZWw9InN0eWxlc2hlZXQiIGhyZWY9InslIHN0YXRp
YyAnZ3VpL2Nzcy9zdHlsZS5jc3MnICV9Ij4KLSAgICA8bGluayByZWw9InN0eWxlc2hlZXQiIGhy
ZWY9InslIHN0YXRpYyAnZ3VpL2Nzcy9zdHlsZS5jc3MnICV9Ij4KICAgICA8c2NyaXB0IHNyYz0i
eyUgc3RhdGljICdndWkvanMvdGhlbWUuanMnICV9Ij48L3NjcmlwdD4KIDwvaGVhZD4KIDxib2R5
PgpAQCAtMjIsNyArMjEsNyBAQAogICAgICAgICB7JSBpZiBub3QgY29uZmlnX2xvYWRlZCAlfW5v
bmUgbG9hZGVkCiAgICAgICAgIHslIGVsaWYgY29uZmlnX2RpcnR5ICV9PHN0cm9uZz5VbnNhdmVk
IGNoYW5nZXM8L3N0cm9uZz4KICAgICAgICAgeyUgZWxzZSAlfW5vIHVuc2F2ZWQgY2hhbmdlc3sl
IGVuZGlmICV9Ci0gICAgICAgIDwvc3Bhbj4KKyAgICA8L3NwYW4+CiAgICAgPGJ1dHRvbiB0eXBl
PSJidXR0b24iIGlkPSJ0aGVtZS10b2dnbGUiIGNsYXNzPSJ0aGVtZS10b2dnbGUiIGFyaWEtcHJl
c3NlZD0iZmFsc2UiPkRhcmsgbW9kZTwvYnV0dG9uPgogPC9uYXY+CiA8bWFpbiBpZD0ibWFpbiI+
CmRpZmYgLS1naXQgYS9ndWkvdGVtcGxhdGVzL2d1aS9jb25maWdfZWRpdG9yLmh0bWwgYi9ndWkv
dGVtcGxhdGVzL2d1aS9jb25maWdfZWRpdG9yLmh0bWwKaW5kZXggMTYyNzBjZi4uMzNjYmFmYiAx
MDA2NDQKLS0tIGEvZ3VpL3RlbXBsYXRlcy9ndWkvY29uZmlnX2VkaXRvci5odG1sCisrKyBiL2d1
aS90ZW1wbGF0ZXMvZ3VpL2NvbmZpZ19lZGl0b3IuaHRtbApAQCAtNjcsMTEgKzY3LDExIEBACiAg
ICAgICAgICAgICBpdCBnb2VzIGFuZCBhc2tzIGJlZm9yZSByZXBsYWNpbmcgYW4gZXhpc3Rpbmcg
ZmlsZS4gVmFsaWRhdGluZyByZS1jaGVja3MgZXZlcnkgcnVsZSB3aXRob3V0IHNhdmluZy4KICAg
ICAgICAgPC9wPgogICAgICAgICA8ZGl2IGNsYXNzPSJidXR0b24tcm93Ij4KLSAgICAgICAgICAg
IDxmb3JtIG1ldGhvZD0icG9zdCIgYWN0aW9uPSJ7JSB1cmwgJ2d1aTpjb25maWdfc2F2ZScgJX0i
PgorICAgICAgICAgICAgPGZvcm0gbWV0aG9kPSJwb3N0IiBhY3Rpb249InslIHVybCAnZ3VpOmNv
bmZpZ19zYXZlJyAlfSIgZGF0YS1sb2FkaW5nPSJMb2FkaW5n4oCmIiBkYXRhLWxvYWRpbmctZG93
bmxvYWQ+CiAgICAgICAgICAgICAgICAgeyUgY3NyZl90b2tlbiAlfQogICAgICAgICAgICAgICAg
IDxidXR0b24gdHlwZT0ic3VibWl0IiBjbGFzcz0iYnRuIGJ0bi1wcmltYXJ5InslIGlmIG5vdCBo
YXNfY29uZmlnICV9IGRpc2FibGVkeyUgZW5kaWYgJX0+U2F2ZSBjb25maWd1cmF0aW9uPC9idXR0
b24+CiAgICAgICAgICAgICA8L2Zvcm0+Ci0gICAgICAgICAgICA8Zm9ybSBtZXRob2Q9InBvc3Qi
IGFjdGlvbj0ieyUgdXJsICdndWk6Y29uZmlnX3ZhbGlkYXRlJyAlfSI+CisgICAgICAgICAgICA8
Zm9ybSBtZXRob2Q9InBvc3QiIGFjdGlvbj0ieyUgdXJsICdndWk6Y29uZmlnX3ZhbGlkYXRlJyAl
fSIgZGF0YS1sb2FkaW5nPSJWYWxpZGF0aW5n4oCmIj4KICAgICAgICAgICAgICAgICB7JSBjc3Jm
X3Rva2VuICV9CiAgICAgICAgICAgICAgICAgPGJ1dHRvbiB0eXBlPSJzdWJtaXQiIGNsYXNzPSJi
dG4ieyUgaWYgbm90IGhhc19jb25maWcgJX0gZGlzYWJsZWR7JSBlbmRpZiAlfT5WYWxpZGF0ZSBj
b25maWd1cmF0aW9uPC9idXR0b24+CiAgICAgICAgICAgICA8L2Zvcm0+CkBAIC04NCw3ICs4NCw3
IEBACiAgICAgICAgICAgICBBIG5ldyBjb25maWd1cmF0aW9uIGJlZ2lucyB3aXRoIG9uZSBwbGFj
ZWhvbGRlciByb29tLCBjb3Vyc2UsIGZhY3VsdHkgbWVtYmVyIGFuZCBjbGFzcyBwYXR0ZXJuLCBi
ZWNhdXNlIHRoZQogICAgICAgICAgICAgc2NoZWR1bGVyIGRvZXMgbm90IGFjY2VwdCBhIGNvbXBs
ZXRlbHkgZW1wdHkgb25lLiBFZGl0IG9yIHJlcGxhY2UgdGhlbSBhcyB5b3UgYnVpbGQgcmVhbCBk
YXRhLgogICAgICAgICA8L3A+Ci0gICAgICAgIDxmb3JtIG1ldGhvZD0icG9zdCIgYWN0aW9uPSJ7
JSB1cmwgJ2d1aTpjb25maWdfbmV3JyAlfSIgY2xhc3M9ImVkaXQtZm9ybSI+CisgICAgICAgIDxm
b3JtIG1ldGhvZD0icG9zdCIgYWN0aW9uPSJ7JSB1cmwgJ2d1aTpjb25maWdfbmV3JyAlfSIgY2xh
c3M9ImVkaXQtZm9ybSIgZGF0YS1sb2FkaW5nPSJMb2FkaW5n4oCmIj4KICAgICAgICAgICAgIHsl
IGNzcmZfdG9rZW4gJX0KICAgICAgICAgICAgIHslIGluY2x1ZGUgImd1aS9jb21wb25lbnRzL2Zv
cm1fZmllbGRzLmh0bWwiIHdpdGggZm9ybT1uZXdfZm9ybSAlfQogICAgICAgICAgICAgPGJ1dHRv
biB0eXBlPSJzdWJtaXQiIGNsYXNzPSJidG4iPlN0YXJ0IG5ldyBjb25maWd1cmF0aW9uPC9idXR0
b24+CkBAIC05Nyw3ICs5Nyw3IEBACiAgICAgICAgICAgICBUaGUgd2hvbGUgZmlsZSBpcyBjaGVj
a2VkIGJlZm9yZSBhbnl0aGluZyBjaGFuZ2VzLiBJZiBpdCBoYXMgYSBwcm9ibGVtLCB5b3Ugd2ls
bCBzZWUgd2hhdCBpcyB3cm9uZyBhbmQgdGhlCiAgICAgICAgICAgICBjb25maWd1cmF0aW9uIHlv
dSBoYXZlIG5vdyBzdGF5cyBhcyBpdCBpcy4KICAgICAgICAgPC9wPgotICAgICAgICA8Zm9ybSBt
ZXRob2Q9InBvc3QiIGFjdGlvbj0ieyUgdXJsICdndWk6Y29uZmlnX2xvYWQnICV9IiBlbmN0eXBl
PSJtdWx0aXBhcnQvZm9ybS1kYXRhIiBjbGFzcz0iZWRpdC1mb3JtIj4KKyAgICAgICAgPGZvcm0g
bWV0aG9kPSJwb3N0IiBhY3Rpb249InslIHVybCAnZ3VpOmNvbmZpZ19sb2FkJyAlfSIgZW5jdHlw
ZT0ibXVsdGlwYXJ0L2Zvcm0tZGF0YSIgY2xhc3M9ImVkaXQtZm9ybSIgZGF0YS1sb2FkaW5nPSJM
b2FkaW5n4oCmIj4KICAgICAgICAgICAgIHslIGNzcmZfdG9rZW4gJX0KICAgICAgICAgICAgIHsl
IGluY2x1ZGUgImd1aS9jb21wb25lbnRzL2Zvcm1fZmllbGRzLmh0bWwiIHdpdGggZm9ybT1sb2Fk
X2Zvcm0gJX0KICAgICAgICAgICAgIDxidXR0b24gdHlwZT0ic3VibWl0IiBjbGFzcz0iYnRuIGJ0
bi1wcmltYXJ5Ij5Mb2FkIGNvbmZpZ3VyYXRpb248L2J1dHRvbj4K