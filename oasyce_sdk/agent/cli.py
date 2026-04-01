"""oasyce-agent CLI — unified data asset management.

Daemon:
    oasyce-agent start          # launch background daemon
    oasyce-agent stop           # stop daemon
    oasyce-agent status         # check daemon + show stats

Manual:
    oasyce-agent scan <path>    # scan directory, show classification + privacy
    oasyce-agent privacy <file> # check single file for PII
    oasyce-agent stats          # show registered asset breakdown
    oasyce-agent run            # foreground mode (for debugging)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import daemon


def _print_banner():
    C = "\033[36m"   # cyan
    B = "\033[96m"   # bright cyan
    W = "\033[97m"   # bright white
    D = "\033[90m"   # dim gray
    R = "\033[0m"    # reset
    print(f"""
{D}  ┌───────────────────────────────────────────┐{R}
{D}  │                                           │{R}
{D}  │  {B} ██████   █████  ███████ ██    ██  ██████ ███████{R}
{D}  │  {B}██    ██ ██   ██ ██       ██  ██  ██      ██{R}
{D}  │  {C}██    ██ ███████ ███████   ████   ██      █████{R}
{D}  │  {C}██    ██ ██   ██      ██    ██    ██      ██{R}
{D}  │  {D} ██████  ██   ██ ███████    ██     ██████ ███████{R}
{D}  │                                           │{R}
{D}  │  {W}agent{R}                          {D}v0.8.3{R}   {D}│{R}
{D}  └───────────────────────────────────────────┘{R}
""")


def _human_size(size: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------

_TRADE_PROFILES = {
    "a": {
        "label": "Conservative",
        "desc": "earn only, never spend",
        "auto_trade": False,
        "trade_tags": [],
        "trade_max_spend_uoas": 0,
    },
    "b": {
        "label": "Balanced",
        "desc": "≤1 OAS/day on useful capabilities",
        "auto_trade": True,
        "trade_tags": ["ai", "nlp", "data", "analytics"],
        "trade_max_spend_uoas": 1_000_000,
    },
    "c": {
        "label": "Aggressive",
        "desc": "actively discover and trade",
        "auto_trade": True,
        "trade_tags": ["ai", "nlp", "data", "analytics", "code", "translation"],
        "trade_max_spend_uoas": 10_000_000,
    },
}


def _first_run_setup(config_path: str):
    """Interactive first-run: 2 questions, then the agent runs forever."""
    from . import scanner

    print("  First time? 2 questions, then I run forever.\n")

    # --- Question 1: scan paths ---
    defaults = scanner.DEFAULT_SCAN_PATHS
    short = [os.path.basename(p) for p in defaults]
    print(f"  1. Scan directories:")
    print(f"     {', '.join(short)}")
    extra = input("     Add more? (path or enter to skip): ").strip()

    scan_paths = list(defaults)
    if extra:
        expanded = os.path.expanduser(extra)
        if os.path.isdir(expanded):
            scan_paths.append(expanded)
            print(f"     + {expanded}")
        else:
            print(f"     '{extra}' not found, skipping")

    # --- Question 2: trading style ---
    print()
    print("  2. Trading style:")
    print("     a) Conservative — earn only, never spend")
    print("     b) Balanced     — ≤1 OAS/day on useful capabilities")
    print("     c) Aggressive   — actively discover and trade")
    choice = input("     Choose [a/b/c] (default: b): ").strip().lower() or "b"
    profile = _TRADE_PROFILES.get(choice, _TRADE_PROFILES["b"])

    # --- Privacy notice ---
    print()
    print("  Privacy: only safe files register. Always on. Non-negotiable.")

    # --- Save config ---
    config = {
        "node_url": "http://47.93.32.88:1317",
        "chain_id": "oasyce-testnet-1",
        "interval_seconds": 3600,
        "max_per_cycle": 10,
        "scan_paths": scan_paths,
        "max_file_size_mb": 50,
        "auto_trade": profile["auto_trade"],
        "trade_tags": profile["trade_tags"],
        "trade_max_spend_uoas": profile["trade_max_spend_uoas"],
    }

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n  Ready.")
    print(f"  Scanning: {len(scan_paths)} directories")
    print(f"  Trading:  {profile['label']} — {profile['desc']}")
    print()


# ---------------------------------------------------------------------------
# Daemon commands
# ---------------------------------------------------------------------------

def cmd_start(args):
    _print_banner()

    config_path = os.path.join(daemon.OASYCE_DIR, "agent.json")
    if not os.path.exists(config_path):
        _first_run_setup(config_path)

    ok, msg = daemon.start()
    print(msg)
    if ok:
        print(f"\n  Config:  {config_path}")
        print(f"  Wallet:  {os.path.join(daemon.OASYCE_DIR, 'wallet.json')}")
        print(f"  Logs:    {daemon.LOG_FILE}")
        print(f"\n  oasyce-agent status   # check progress")
        print(f"  oasyce-agent stop     # stop agent")
    sys.exit(0 if ok else 1)


def cmd_stop(args):
    ok, msg = daemon.stop()
    print(msg)
    sys.exit(0 if ok else 1)


def cmd_status(args):
    running, msg = daemon.status()
    print(msg)

    # Show stats from DB
    _print_db_summary()

    # Show wallet address
    _print_wallet()

    sys.exit(0 if running else 1)


def cmd_run(args):
    """Foreground mode — used by daemon internally, also for debugging."""
    from .core import run_forever
    run_forever()


# ---------------------------------------------------------------------------
# Manual commands
# ---------------------------------------------------------------------------

def cmd_scan(args):
    """Scan a directory: classify + privacy check + report."""
    from . import scanner

    path = os.path.expanduser(args.path)
    if not os.path.isdir(path):
        print(f"Error: {path} is not a directory")
        sys.exit(1)

    print(f"Scanning {path}...")
    files = scanner.scan(paths=[path], check_privacy=True)

    if not files:
        print("No files found.")
        return

    # Aggregate stats
    categories = {}
    risks = {}
    total_size = 0
    for f in files:
        categories[f.category] = categories.get(f.category, 0) + 1
        risks[f.privacy_risk] = risks.get(f.privacy_risk, 0) + 1
        total_size += f.size

    # Print summary
    print(f"\n{'=' * 50}")
    print(f"  {len(files)} files | {_human_size(total_size)}")
    print(f"{'=' * 50}")

    print("\nCategories:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat:12s}  {count}")

    print("\nPrivacy risk:")
    risk_order = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    for risk, count in sorted(risks.items(), key=lambda x: risk_order.get(x[0], 9)):
        marker = "" if risk == "safe" else " <-- blocked"
        print(f"  {risk:12s}  {count}{marker}")

    safe_count = risks.get("safe", 0)
    blocked = len(files) - safe_count
    print(f"\nRegisterable: {safe_count} files")
    if blocked:
        print(f"Blocked (PII): {blocked} files")

    # Show risky files if any
    risky_files = [f for f in files if f.privacy_risk != "safe"]
    if risky_files and not args.json:
        print(f"\nFiles with PII detected:")
        for f in risky_files[:20]:
            print(f"  [{f.privacy_risk:8s}] {f.name}")
        if len(risky_files) > 20:
            print(f"  ... and {len(risky_files) - 20} more")

    if args.json:
        output = {
            "total": len(files),
            "total_size": total_size,
            "categories": categories,
            "risks": risks,
            "files": [
                {
                    "name": f.name,
                    "path": f.path,
                    "sha256": f.sha256,
                    "size": f.size,
                    "category": f.category,
                    "privacy_risk": f.privacy_risk,
                }
                for f in files
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))


def cmd_privacy(args):
    """Check a single file or directory for PII."""
    from . import privacy, scanner

    path = os.path.expanduser(args.path)

    if os.path.isfile(path):
        findings = privacy.scan_file(path)
        risk = privacy.risk_level(findings)
        print(f"File: {path}")
        print(f"Risk: {risk}")
        if findings["has_sensitive"]:
            for item in findings["findings"]:
                print(f"  {item['type']}: {item['count']} occurrence(s) (sample: {item['sample']})")
        else:
            print("  No PII detected")
    elif os.path.isdir(path):
        print(f"Scanning {path} for PII...")
        files = scanner.scan(paths=[path], check_privacy=True)
        risky = [f for f in files if f.privacy_risk != "safe"]
        print(f"\nTotal files: {len(files)}")
        print(f"Safe: {len(files) - len(risky)}")
        print(f"PII detected: {len(risky)}")
        if risky:
            print(f"\nFiles with PII:")
            for f in risky:
                print(f"  [{f.privacy_risk:8s}] {f.name}")
    else:
        print(f"Error: {path} not found")
        sys.exit(1)


def cmd_join(args):
    """Join an existing owner account by importing a mnemonic."""
    from oasyce_sdk.crypto.wallet import Wallet

    wallet_path = os.path.join(daemon.OASYCE_DIR, "wallet.json")
    if os.path.exists(wallet_path):
        with open(wallet_path) as f:
            data = json.load(f)
        existing = data.get("address", "unknown")
        if not args.force:
            print(f"Wallet already exists: {existing}")
            print("Use --force to overwrite.")
            sys.exit(1)

    mnemonic = args.mnemonic
    try:
        w = Wallet.from_mnemonic(mnemonic)
    except Exception as e:
        print(f"Invalid mnemonic: {e}")
        sys.exit(1)

    os.makedirs(daemon.OASYCE_DIR, exist_ok=True)
    with open(wallet_path, "w") as f:
        json.dump({"mnemonic": mnemonic, "address": w.address}, f, indent=2)

    if sys.platform != "win32":
        import stat
        os.chmod(wallet_path, stat.S_IRUSR | stat.S_IWUSR)

    print(f"Joined: {w.address}")
    print(f"This device now operates under the same owner account.")
    print(f"\n  oasyce-agent start   # begin scanning on this device")


def cmd_stats(args):
    """Show registered asset statistics."""
    _print_db_summary(verbose=True)
    _print_wallet()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_db_summary(verbose: bool = False):
    db_path = os.path.join(daemon.OASYCE_DIR, "agent.db")
    if not os.path.exists(db_path):
        print("No agent data yet. Run: oasyce-agent start")
        return

    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM registered_assets").fetchone()[0]
        print(f"\nRegistered assets: {count}")

        if verbose and count > 0:
            # Category breakdown
            try:
                rows = conn.execute(
                    "SELECT category, COUNT(*) FROM registered_assets GROUP BY category ORDER BY COUNT(*) DESC"
                ).fetchall()
                if rows:
                    print("\nBy category:")
                    for cat, cnt in rows:
                        print(f"  {cat or 'unknown':12s}  {cnt}")
            except Exception:
                pass

            # Recent registrations
            try:
                rows = conn.execute(
                    "SELECT file_name, registered_at FROM registered_assets ORDER BY registered_at DESC LIMIT 5"
                ).fetchall()
                if rows:
                    print("\nRecent:")
                    for name, ts in rows:
                        print(f"  {ts[:19]}  {name}")
            except Exception:
                pass
    except Exception:
        pass
    conn.close()


def _print_wallet():
    wp = os.path.join(daemon.OASYCE_DIR, "wallet.json")
    if os.path.exists(wp):
        with open(wp) as f:
            data = json.load(f)
        addr = data.get("address")
        if addr:
            print(f"Wallet: {addr}")
            return
    print("Wallet: not created yet")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="oasyce-agent",
        description="Oasyce data agent — scan, protect, register, automate",
    )
    sub = parser.add_subparsers(dest="command")

    # Daemon
    sub.add_parser("start", help="Start agent in background")
    sub.add_parser("stop", help="Stop agent")
    sub.add_parser("status", help="Show agent status")
    sub.add_parser("run", help="Run in foreground (for debugging)")

    # Identity
    p_join = sub.add_parser("join", help="Join existing owner account (import mnemonic)")
    p_join.add_argument("mnemonic", help="24-word BIP39 mnemonic")
    p_join.add_argument("--force", action="store_true", help="Overwrite existing wallet")

    # Manual
    p_scan = sub.add_parser("scan", help="Scan directory (classify + privacy)")
    p_scan.add_argument("path", help="Directory to scan")
    p_scan.add_argument("--json", action="store_true", help="JSON output")

    p_priv = sub.add_parser("privacy", help="Check file/directory for PII")
    p_priv.add_argument("path", help="File or directory to check")

    sub.add_parser("stats", help="Show registered asset statistics")

    args = parser.parse_args()

    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "run": cmd_run,
        "join": cmd_join,
        "scan": cmd_scan,
        "privacy": cmd_privacy,
        "stats": cmd_stats,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        _print_banner()
        parser.print_help()
        print("\nQuick start:")
        print("  oasyce-agent start              # new device, new account")
        print("  oasyce-agent join \"word1 ...\"    # join existing account")
        print("  oasyce-agent scan ~/Documents    # one-shot scan")
        sys.exit(1)


if __name__ == "__main__":
    main()
