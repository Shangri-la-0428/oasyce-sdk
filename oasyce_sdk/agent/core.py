"""Agent core — the brain. Auto-wallet, auto-PoW, scan→register→discover→trade→sleep."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import stat
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Set

from . import scanner
from .daemon import OASYCE_DIR

logger = logging.getLogger("oasyce.agent")

DB_PATH = os.path.join(OASYCE_DIR, "agent.db")
WALLET_PATH = os.path.join(OASYCE_DIR, "wallet.json")
CONFIG_PATH = os.path.join(OASYCE_DIR, "agent.json")

DEFAULT_NODE = "http://47.93.32.88:1317"
DEFAULT_CHAIN_ID = "oasyce-testnet-1"
DEFAULT_INTERVAL = 3600  # 1 hour
MAX_PER_CYCLE = 10  # max assets to register per cycle


def _load_config() -> dict:
    """Load or create default config."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)

    config = {
        "node_url": DEFAULT_NODE,
        "chain_id": DEFAULT_CHAIN_ID,
        "interval_seconds": DEFAULT_INTERVAL,
        "max_per_cycle": MAX_PER_CYCLE,
        "scan_paths": scanner.DEFAULT_SCAN_PATHS,
        "max_file_size_mb": 50,
        "auto_trade": False,
        "trade_tags": [],
        "trade_max_spend_uoas": 1_000_000,  # 1 OAS per cycle
    }
    os.makedirs(OASYCE_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    logger.info("Created default config: %s", CONFIG_PATH)
    return config


def _init_db() -> sqlite3.Connection:
    """Initialize SQLite state database."""
    os.makedirs(OASYCE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registered_assets (
            content_hash TEXT PRIMARY KEY,
            file_path TEXT,
            file_name TEXT,
            category TEXT,
            privacy_risk TEXT DEFAULT 'safe',
            tx_hash TEXT,
            registered_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS capability_trades (
            capability_id TEXT,
            invocation_tx TEXT,
            amount_uoas INTEGER,
            tags TEXT,
            traded_at TEXT,
            PRIMARY KEY (capability_id, traded_at)
        )
    """)
    conn.commit()
    return conn


def _get_known_hashes(conn: sqlite3.Connection) -> Set[str]:
    """Load all registered content hashes from DB."""
    cur = conn.execute("SELECT content_hash FROM registered_assets")
    return {row[0] for row in cur.fetchall()}


def _record_asset(conn: sqlite3.Connection, file_info: scanner.FileInfo, tx_hash: str):
    """Record a newly registered asset."""
    conn.execute(
        "INSERT OR IGNORE INTO registered_assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            file_info.sha256,
            file_info.path,
            file_info.name,
            file_info.category,
            file_info.privacy_risk,
            tx_hash,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def _get_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    cur = conn.execute("SELECT value FROM agent_state WHERE key = ?", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def _set_state(conn: sqlite3.Connection, key: str, value: str):
    conn.execute(
        "INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Wallet Management
# ---------------------------------------------------------------------------

def _ensure_wallet():
    """Create wallet if none exists. Returns (Wallet, is_new).

    wallet.json is exclusively the secp256k1 chain wallet.
    If an Ed25519 identity file exists at this path (legacy), it is
    migrated to identity.json to avoid collisions.
    """
    from oasyce_sdk.crypto.wallet import Wallet
    from oasyce_sdk.identity import IdentityResolver

    identity_path = os.path.join(OASYCE_DIR, "identity.json")

    # Migrate legacy Ed25519 identity that was incorrectly stored as wallet.json
    if os.path.exists(WALLET_PATH):
        with open(WALLET_PATH) as f:
            data = json.load(f)
        if "mnemonic" in data:
            w = Wallet.from_mnemonic(data["mnemonic"])
            IdentityResolver.ensure_local_binding(w)
            logger.info("Loaded wallet: %s", w.address)
            return w, False
        elif "private_key" in data:
            w = Wallet.from_private_key(data["private_key"])
            IdentityResolver.ensure_local_binding(w)
            logger.info("Loaded wallet: %s", w.address)
            return w, False
        elif "version" in data and "public_key" in data:
            # Ed25519 identity — move to identity.json, free wallet.json
            if not os.path.exists(identity_path):
                os.rename(WALLET_PATH, identity_path)
                logger.info("Migrated Ed25519 identity → %s", identity_path)
            else:
                os.remove(WALLET_PATH)
                logger.info("Removed stale Ed25519 wallet.json (identity.json exists)")
            # Fall through to create chain wallet

    # Also migrate any .agent hack files from v0.7.0
    agent_path = WALLET_PATH + ".agent"
    if os.path.exists(agent_path):
        with open(agent_path) as f:
            data = json.load(f)
        if "mnemonic" in data and not os.path.exists(WALLET_PATH):
            os.rename(agent_path, WALLET_PATH)
            w = Wallet.from_mnemonic(data["mnemonic"])
            IdentityResolver.ensure_local_binding(w)
            logger.info("Migrated wallet.json.agent → wallet.json: %s", w.address)
            return w, False

    # Fallback: auto-create if no interactive setup happened
    # (e.g. programmatic usage or `oasyce-agent run` without `start`)
    w = Wallet.create()
    os.makedirs(OASYCE_DIR, exist_ok=True)
    with open(WALLET_PATH, "w") as f:
        json.dump({
            "mnemonic": w.mnemonic,
            "address": w.address,
        }, f, indent=2)

    if sys.platform != "win32":
        os.chmod(WALLET_PATH, stat.S_IRUSR | stat.S_IWUSR)

    IdentityResolver.ensure_local_binding(w)
    logger.info("Auto-created wallet (no interactive setup): %s", w.address)
    return w, True


# ---------------------------------------------------------------------------
# PoW Self-Registration
# ---------------------------------------------------------------------------

def _ensure_registered(wallet, client, signer, conn):
    """Check if registered on chain; if not, solve PoW and self-register."""
    if _get_state(conn, "registered") == "true":
        return

    # Check chain
    try:
        client.get_registration(wallet.address)
        _set_state(conn, "registered", "true")
        logger.info("Already registered on chain")
        return
    except Exception:
        pass  # Not found — need to register

    logger.info("Solving PoW for self-registration (this may take a minute)...")
    from oasyce_sdk.client import OasyceClient
    pow_result = OasyceClient.solve_pow(wallet.address, difficulty=16)
    logger.info("PoW solved: nonce=%d, %d attempts", pow_result.nonce, pow_result.attempts)

    result = signer.self_register(pow_result.nonce)
    if result.success:
        _set_state(conn, "registered", "true")
        logger.info("Self-registered! TX: %s", result.tx_hash)
    else:
        logger.warning("Registration TX failed (code %d): %s", result.code, result.raw_log)
        if "already registered" in result.raw_log.lower():
            _set_state(conn, "registered", "true")


# ---------------------------------------------------------------------------
# Discover + Trade
# ---------------------------------------------------------------------------

def _get_traded_ids(conn: sqlite3.Connection) -> Set[str]:
    """Load all previously traded capability IDs."""
    cur = conn.execute("SELECT DISTINCT capability_id FROM capability_trades")
    return {row[0] for row in cur.fetchall()}


def discover_and_trade(client, signer, conn, config) -> int:
    """Discover capabilities by tags, invoke new ones. Returns trade count."""
    if not config.get("auto_trade"):
        return 0

    tags = config.get("trade_tags", [])
    if not tags:
        return 0

    max_spend = config.get("trade_max_spend_uoas", 1_000_000)
    traded_ids = _get_traded_ids(conn)
    spent = 0
    trades = 0

    for tag in tags:
        try:
            caps = client.list_capabilities(tag=tag)
        except Exception as e:
            logger.warning("Discovery failed for tag '%s': %s", tag, e)
            continue

        for cap in caps:
            if cap.id in traded_ids:
                continue
            price = getattr(cap, "price_per_call", 0) or 0
            if spent + price > max_spend:
                logger.info("Trade budget reached (%d/%d uoas)", spent, max_spend)
                return trades

            try:
                result = signer.invoke_capability(cap.id)
                if result.success:
                    conn.execute(
                        "INSERT OR IGNORE INTO capability_trades VALUES (?, ?, ?, ?, ?)",
                        (cap.id, result.tx_hash, price, tag,
                         datetime.now(timezone.utc).isoformat()),
                    )
                    conn.commit()
                    traded_ids.add(cap.id)
                    spent += price
                    trades += 1
                    logger.info("Invoked: %s (%s) TX: %s", cap.name, cap.id, result.tx_hash)
                else:
                    logger.warning("Trade failed for %s: %s", cap.id, result.raw_log)
                    if result.code in (5, 11):
                        logger.warning("Insufficient funds, stopping trades")
                        return trades
            except Exception as e:
                logger.error("Error trading %s: %s", cap.id, e)

            time.sleep(1)

    if trades:
        logger.info("Traded %d capabilities, spent %d uoas", trades, spent)
    else:
        logger.info("No new capabilities to trade")
    return trades


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

def run_once(wallet, client, signer, conn, config) -> int:
    """Run one scan-and-register cycle. Returns number of assets registered."""
    known = _get_known_hashes(conn)
    scan_paths = config.get("scan_paths", scanner.DEFAULT_SCAN_PATHS)
    max_size = config.get("max_file_size_mb", 50) * 1024 * 1024
    max_per = config.get("max_per_cycle", MAX_PER_CYCLE)

    logger.info("Scanning %d directories (%d known assets)...", len(scan_paths), len(known))
    new_files = scanner.scan(
        paths=scan_paths,
        max_size=max_size,
        known_hashes=known,
    )

    if not new_files:
        logger.info("No new files found")
        return 0

    # Iron Rule: only files with privacy_risk == "safe" may auto-register
    safe_files = [f for f in new_files if f.privacy_risk == "safe"]
    risky = len(new_files) - len(safe_files)
    if risky:
        logger.info("Privacy gate: %d safe, %d blocked (PII detected)", len(safe_files), risky)
    if not safe_files:
        logger.info("No safe files to register")
        return 0

    logger.info("Found %d safe files, registering up to %d", len(safe_files), max_per)
    registered = 0

    for file_info in safe_files[:max_per]:
        try:
            result = signer.register_asset(
                name=file_info.name,
                content_hash=file_info.sha256,
                tags=file_info.tags,
                description=f"Auto-registered {file_info.category}: {file_info.name} ({file_info.size} bytes)",
            )
            if result.success:
                _record_asset(conn, file_info, result.tx_hash)
                registered += 1
                logger.info("Registered: %s (TX: %s)", file_info.name, result.tx_hash)
            else:
                logger.warning("TX failed for %s: code=%d %s", file_info.name, result.code, result.raw_log)
                # If out of gas/funds, stop this cycle
                if result.code in (5, 11):
                    logger.warning("Insufficient funds/gas, stopping cycle")
                    break
        except Exception as e:
            logger.error("Error registering %s: %s", file_info.name, e)

        # Brief pause between TXs to avoid sequence issues
        time.sleep(1)

    logger.info("Cycle complete: %d/%d registered", registered, len(new_files))
    return registered


def _ensure_sigil(loop, conn):
    """Ensure this agent has a Sigil on-chain. Idempotent."""
    if _get_state(conn, "sigil_genesis") == "true":
        return

    if loop.on_chain() is not None:
        _set_state(conn, "sigil_genesis", "true")
        logger.info("Sigil already on-chain: %s", loop.sigil_id)
        return

    try:
        loop.genesis(metadata="oasyce-agent auto-genesis")
        _set_state(conn, "sigil_genesis", "true")
        logger.info("Sigil created: %s", loop.sigil_id)
    except Exception as e:
        logger.warning("Sigil genesis failed (will retry): %s", e)


def run_forever():
    """Main daemon entry point. Runs until killed."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    logger.info("=== Oasyce Agent starting ===")

    config = _load_config()
    conn = _init_db()

    # Setup wallet
    wallet, is_new = _ensure_wallet()
    logger.info("Address: %s", wallet.address)

    # Setup SigilManager — the Loop itself
    from oasyce_sdk.sigil import SigilManager

    node_url = config.get("node_url", DEFAULT_NODE)
    chain_id = config.get("chain_id", DEFAULT_CHAIN_ID)

    loop = SigilManager(wallet=wallet, chain_url=node_url, chain_id=chain_id)
    logger.info("Sigil ID: %s", loop.sigil_id)

    # Expose client/signer for scan+register (still needs raw chain ops)
    client = loop.client
    signer = loop.signer

    # Ensure on-chain registration (PoW + airdrop)
    try:
        _ensure_registered(wallet, client, signer, conn)
    except Exception as e:
        logger.warning("Could not register on chain (will retry): %s", e)

    # Ensure Sigil exists on-chain (after registration, so we have gas)
    _ensure_sigil(loop, conn)

    interval = config.get("interval_seconds", DEFAULT_INTERVAL)
    logger.info("Scan interval: %ds, node: %s", interval, node_url)

    cycle = 0
    while True:
        cycle += 1
        logger.info("--- Cycle %d ---", cycle)

        # Announce presence + discover peers
        loop.ping(capability="data-asset-management")
        if cycle % 10 == 1:  # attempt bond every 10 cycles
            new_bonds = loop.auto_bond()
            if new_bonds:
                logger.info("New bonds: %s", new_bonds)

        scan_paths = config.get("scan_paths", scanner.DEFAULT_SCAN_PATHS)
        loop.perceive(f"cycle {cycle}: scanning {len(scan_paths)} directories for data assets")

        try:
            registered = run_once(wallet, client, signer, conn, config)
            trades = discover_and_trade(client, signer, conn, config)
            loop.act(
                f"cycle {cycle}: registered {registered} assets, traded {trades} capabilities",
                "succeeded" if registered + trades > 0 else "partial",
                f"data asset scanning cycle {cycle}",
                capability="data-asset-management",
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error("Cycle error: %s", e)
            loop.act(f"cycle {cycle} failed: {e}", "failed",
                     f"data asset scanning cycle {cycle}", capability="data-asset-management")

        logger.info("Sleeping %ds until next cycle...", interval)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down")
            break

    loop.close()
    conn.close()
    logger.info("=== Oasyce Agent stopped ===")
