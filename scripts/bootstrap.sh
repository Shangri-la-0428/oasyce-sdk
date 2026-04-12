#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Oasyce Full-Stack Bootstrap
#
# One command to install and wire up the complete Oasyce local stack:
#   Thronglets (shared substrate) + Psyche (self-state kernel) + SDK (chain bridge)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Shangri-la-0428/oasyce-sdk/main/scripts/bootstrap.sh | bash
#
# What it does:
#   1. Check prerequisites (Node.js >= 22, Python >= 3.10)
#   2. Install Thronglets via npx
#   3. Install Psyche via npx
#   4. Install oasyce-sdk via pip
#   5. Run `oasyce start` to orchestrate everything
#
# What it does NOT do:
#   - Run a chain node (uses public testnet at 47.93.32.88)
#   - Touch your existing Python/Node environments beyond pip/npx
#   - Require sudo
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Formatting ────────────────────────────────────────────────────────
bold()  { printf "\033[1m%s\033[0m" "$*"; }
green() { printf "\033[32m%s\033[0m" "$*"; }
red()   { printf "\033[31m%s\033[0m" "$*"; }
dim()   { printf "\033[2m%s\033[0m" "$*"; }

step() { printf "\n$(bold "[%s/5]") %s\n" "$1" "$2"; }
ok()   { printf "  $(green "✓") %s\n" "$*"; }
skip() { printf "  $(dim "⏭") %s\n" "$*"; }
fail() { printf "  $(red "✗") %s\n" "$*"; }

# ── Step 0: Prerequisites ────────────────────────────────────────────
step 0 "Checking prerequisites"

HAS_NODE=false
HAS_NPX=false
HAS_PYTHON=false
HAS_PIP=false
ISSUES=()

# Node.js
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/^v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 22 ]; then
        ok "Node.js $NODE_VER"
        HAS_NODE=true
    else
        fail "Node.js $NODE_VER found, need >= 22"
        ISSUES+=("Node.js >= 22 required for Psyche. Install: https://nodejs.org")
    fi
else
    fail "Node.js not found"
    ISSUES+=("Node.js >= 22 required. Install: https://nodejs.org")
fi

# npx
if command -v npx &>/dev/null; then
    HAS_NPX=true
    ok "npx available"
else
    fail "npx not found"
    ISSUES+=("npx required (comes with Node.js)")
fi

# Python
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY_VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
            PYTHON_CMD="$cmd"
            HAS_PYTHON=true
            ok "Python $PY_VER ($cmd)"
            break
        fi
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    fail "Python >= 3.10 not found"
    ISSUES+=("Python >= 3.10 required. Install: https://python.org")
fi

# pip
if $HAS_PYTHON; then
    if "$PYTHON_CMD" -m pip --version &>/dev/null; then
        HAS_PIP=true
        ok "pip available"
    else
        fail "pip not found"
        ISSUES+=("pip required: $PYTHON_CMD -m ensurepip --upgrade")
    fi
fi

# Bail if critical prerequisites missing
if [ ${#ISSUES[@]} -gt 0 ]; then
    printf "\n$(red "Missing prerequisites:")\n"
    for issue in "${ISSUES[@]}"; do
        printf "  - %s\n" "$issue"
    done
    printf "\nFix the above, then re-run this script.\n"
    exit 1
fi

# ── Step 1: Thronglets ───────────────────────────────────────────────
step 1 "Installing Thronglets (shared substrate)"

if command -v thronglets &>/dev/null; then
    THRONGLETS_VER=$(thronglets --version 2>/dev/null || echo "installed")
    skip "Thronglets already installed ($THRONGLETS_VER)"
else
    npx -y thronglets start || {
        fail "Thronglets install failed (non-blocking, continuing)"
    }
    ok "Thronglets installed + hooks configured"
fi

# ── Step 2: Psyche ───────────────────────────────────────────────────
step 2 "Installing Psyche (self-state kernel)"

if npx -y psyche-ai --version &>/dev/null 2>&1; then
    skip "Psyche already available"
    npx -y psyche-ai setup || {
        fail "Psyche setup failed (non-blocking, continuing)"
    }
    ok "Psyche MCP configured"
else
    npx -y psyche-ai setup || {
        fail "Psyche install failed (non-blocking, continuing)"
    }
    ok "Psyche installed + MCP configured"
fi

# ── Step 3: oasyce-sdk ───────────────────────────────────────────────
step 3 "Installing oasyce-sdk (chain bridge + data agent + MCP)"

PIP_FLAGS=(--user -U)

# Detect externally-managed Python (Homebrew, system, etc.)
if "$PYTHON_CMD" -c "import sysconfig; exit(0 if sysconfig.get_path('purelib').startswith('/usr') else 1)" 2>/dev/null; then
    if "$PYTHON_CMD" -m pip install --user --dry-run oasyce-sdk 2>&1 | grep -q "externally-managed"; then
        PIP_FLAGS+=(--break-system-packages)
    fi
fi

"$PYTHON_CMD" -m pip install "${PIP_FLAGS[@]}" "oasyce-sdk[all]" || {
    # Fallback: try pipx
    if command -v pipx &>/dev/null; then
        pipx install "oasyce-sdk[all]" || pipx upgrade "oasyce-sdk[all]"
        ok "Installed via pipx"
    else
        fail "pip install failed. Try: pipx install oasyce-sdk[all]"
        exit 1
    fi
}
ok "oasyce-sdk installed"

# ── Step 4: Unified orchestration ────────────────────────────────────
step 4 "Running oasyce start (unified orchestration)"

printf "  $(dim "This will: resolve identity → chain readiness → wire Thronglets + Psyche → start agent")\n\n"

oasyce start || {
    fail "oasyce start exited with errors (check warnings above)"
}

# ── Step 5: Verify ───────────────────────────────────────────────────
step 5 "Verifying stack"

printf "\n"
oasyce status 2>/dev/null || true

printf "\n$(bold "━━━ Oasyce full stack is ready ━━━")\n\n"
printf "  $(bold "Next steps:")\n"
printf "    oasyce status          — check local stack health\n"
printf "    oasyce share           — share access to another device\n"
printf "    oasyce-agent scan ~/   — scan local files for data assets\n"
printf "\n"
printf "  $(bold "For AI tools (Claude Code / Cursor / Windsurf):")\n"
printf "    MCP servers were auto-configured during setup.\n"
printf "    Restart your AI tool to load the new MCP connections.\n"
printf "\n"
printf "  $(bold "Docs:")\n"
printf "    SDK:         https://github.com/Shangri-la-0428/oasyce-sdk\n"
printf "    Thronglets:  https://github.com/Shangri-la-0428/Thronglets\n"
printf "    Psyche:      https://github.com/Shangri-la-0428/artificial-psyche\n"
printf "    Chain:       https://github.com/Shangri-la-0428/oasyce-chain\n"
printf "\n"
