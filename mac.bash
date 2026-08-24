#!/usr/bin/env bash
#
# win-ssh-copy-id.sh — a working ssh-copy-id for Windows OpenSSH servers.
#
# The stock ssh-copy-id assumes a POSIX shell on the far end and quietly does
# nothing useful against Windows. This does the equivalent properly:
#
#   * generates a key pair if you don't have one
#   * works out whether the remote account is an Administrator, and picks
#     C:\ProgramData\ssh\administrators_authorized_keys or ~/.ssh/authorized_keys
#     accordingly (sshd ignores the latter for admins — the usual gotcha)
#   * sets the ACLs sshd demands, or it silently rejects the file
#   * is idempotent: re-running won't duplicate the key
#   * verifies passwordless login actually works at the end
#
# Usage:
#   ./win-ssh-copy-id.sh raf-win
#   ./win-ssh-copy-id.sh rafael@192.168.1.15 ~/.ssh/id_rsa
#   ./win-ssh-copy-id.sh raf-win --print-only   # emit PowerShell to paste manually
#
set -euo pipefail

TARGET="${1:-}"
KEY="${2:-$HOME/.ssh/id_ed25519}"
PRINT_ONLY=0

for arg in "$@"; do
    [[ "$arg" == "--print-only" ]] && PRINT_ONLY=1
done
[[ "$KEY" == "--print-only" ]] && KEY="$HOME/.ssh/id_ed25519"

if [[ -z "$TARGET" || "$TARGET" == "--print-only" ]]; then
    echo "usage: $0 <ssh-host-or-alias> [private-key-path] [--print-only]" >&2
    exit 2
fi

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m  %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Make sure we have a key pair
# ---------------------------------------------------------------------------

if [[ ! -f "$KEY" ]]; then
    say "No private key at $KEY — generating an ed25519 pair."
    ssh-keygen -t ed25519 -f "$KEY" -C "$(whoami)@$(hostname -s)"
fi

PUB="${KEY}.pub"
if [[ ! -f "$PUB" ]]; then
    say "Public half missing — deriving it from the private key."
    ssh-keygen -y -f "$KEY" > "$PUB"
fi

PUBKEY="$(tr -d '\r\n' < "$PUB")"
[[ -n "$PUBKEY" ]] || die "Public key file $PUB is empty."

case "$PUBKEY" in
    ssh-ed25519*|ecdsa-*|sk-*) ;;
    ssh-rsa*)
        warn "This is an RSA key. Modern OpenSSH rejects SHA-1 signatures, so an"
        warn "old key may be offered and silently ignored. If this fails, generate"
        warn "an ed25519 key and retry."
        ;;
    *) die "Doesn't look like a public key: ${PUBKEY:0:40}..." ;;
esac

say "Key: ${PUBKEY%% *} ... ${PUBKEY##* }"

# ---------------------------------------------------------------------------
# 2. Build the remote PowerShell
# ---------------------------------------------------------------------------
# Single quotes are doubled for PowerShell's escaping rules. Public keys don't
# normally contain quotes, but the comment field can be anything.

ESCAPED_KEY="${PUBKEY//\'/\'\'}"

read -r -d '' PS_SCRIPT <<PSEOF || true
\$ErrorActionPreference = 'Stop'
\$key = '${ESCAPED_KEY}'

# Group membership by well-known SID, not name — survives localised Windows and
# tells us the truth even when the SSH session token isn't elevated.
\$adminSid = New-Object System.Security.Principal.SecurityIdentifier 'S-1-5-32-544'
\$isAdmin  = ([Security.Principal.WindowsIdentity]::GetCurrent()).Groups -contains \$adminSid

if (\$isAdmin) {
    \$target = 'C:\ProgramData\ssh\administrators_authorized_keys'
    \$dir    = 'C:\ProgramData\ssh'
} else {
    \$target = Join-Path \$env:USERPROFILE '.ssh\authorized_keys'
    \$dir    = Join-Path \$env:USERPROFILE '.ssh'
}

Write-Output "ACCOUNT: \$env:USERNAME (admin: \$isAdmin)"
Write-Output "TARGET: \$target"

try {
    if (-not (Test-Path \$dir)) { New-Item -ItemType Directory -Force -Path \$dir | Out-Null }
    if (-not (Test-Path \$target)) { New-Item -ItemType File -Force -Path \$target | Out-Null }

    \$existing = @(Get-Content \$target -ErrorAction SilentlyContinue)
    if (\$existing -contains \$key) {
        Write-Output "RESULT: key already present, nothing to do"
    } else {
        Add-Content -Path \$target -Value \$key -Encoding ascii
        Write-Output "RESULT: key appended"
    }

    # sshd refuses the file outright if anyone else can write it.
    if (\$isAdmin) {
        icacls \$target /inheritance:r | Out-Null
        icacls \$target /grant 'Administrators:F' 'SYSTEM:F' | Out-Null
    } else {
        icacls \$target /inheritance:r | Out-Null
        icacls \$target /grant "\$(\$env:USERNAME):F" 'SYSTEM:F' | Out-Null
    }
    Write-Output "RESULT: acl set"
} catch {
    Write-Output "FAILED: \$(\$_.Exception.Message)"
    exit 1
}

# Sanity-check the server config while we're here.
\$cfg = 'C:\ProgramData\ssh\sshd_config'
if (Test-Path \$cfg) {
    \$c = Get-Content \$cfg
    if (\$c -match '^\s*PubkeyAuthentication\s+no') { Write-Output "WARN: PubkeyAuthentication is set to no in sshd_config" }
    if (\$c -match '^\s*AuthorizedKeysFile\s+__PROGRAMDATA__') { Write-Output "NOTE: AuthorizedKeysFile is overridden in sshd_config" }
}
Write-Output "DONE"
PSEOF

if [[ $PRINT_ONLY -eq 1 ]]; then
    say "PowerShell to run in an ELEVATED window on the Windows machine:"
    echo
    printf '%s\n' "$PS_SCRIPT"
    exit 0
fi

# PowerShell's -EncodedCommand wants UTF-16LE base64 on a single line. Going
# through this avoids every quoting problem between bash, cmd.exe and pwsh.
if command -v iconv >/dev/null 2>&1; then
    ENCODED="$(printf '%s' "$PS_SCRIPT" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')"
else
    die "iconv not found; can't encode the remote command."
fi

# ---------------------------------------------------------------------------
# 3. Push it
# ---------------------------------------------------------------------------

say "Connecting to $TARGET (you'll be asked for the Windows password)."

set +e
OUTPUT="$(ssh -o PreferredAuthentications=password,keyboard-interactive \
              -o PubkeyAuthentication=no \
              "$TARGET" "powershell -NoProfile -NonInteractive -EncodedCommand $ENCODED" 2>&1)"
RC=$?
set -e

printf '%s\n' "$OUTPUT" | sed 's/^/    /'

if [[ $RC -ne 0 || "$OUTPUT" == *FAILED:* ]]; then
    warn "Remote step failed. This is usually because the SSH session got a"
    warn "non-elevated token and couldn't write to C:\\ProgramData\\ssh."
    warn "Re-run with --print-only and paste the output into an elevated"
    warn "PowerShell window on the Windows machine instead."
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. Verify
# ---------------------------------------------------------------------------

say "Testing passwordless login."

if ssh -o BatchMode=yes \
       -o PreferredAuthentications=publickey \
       -o IdentitiesOnly=yes \
       -i "$KEY" \
       "$TARGET" "echo ok" 2>/dev/null | grep -q ok; then
    say "Working. ssh $TARGET should no longer prompt."
else
    warn "Still prompting. Check the server log on the Windows box:"
    warn "    Get-Content C:\\ProgramData\\ssh\\logs\\sshd.log -Tail 40"
    warn "'bad ownership or modes' there means the ACL didn't take."
    warn "Also add 'IdentitiesOnly yes' to your Host block — without it the"
    warn "client may burn through its attempt limit offering other keys first."
    exit 1
fi
