#!/usr/bin/env python3
"""Full Agent Lifecycle Example — Oasyce SDK

Demonstrates the complete flow an AI agent goes through on the Oasyce network:

  1. Self-register via PoW (no KYC)
  2. Register an AI capability
  3. Another agent invokes the capability
  4. Provider completes invocation (challenge window starts)
  5. Provider claims payment (after challenge window)
  6. Consumer submits feedback
  7. Register a data asset + buy/sell shares (bonding curve)

Prerequisites:
  - Oasyce chain running locally (make build && scripts/start_testnet.sh)
  - Two funded accounts in test keyring
  - pip install oasyce-sdk

Usage:
  python examples/full_agent_lifecycle.py [--base-url http://localhost:1317]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time

from oasyce_sdk import OasyceClient


def step(n: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Step {n}: {title}")
    print(f"{'='*60}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Oasyce full agent lifecycle demo")
    parser.add_argument("--base-url", default="http://localhost:1317", help="Chain REST API")
    parser.add_argument("--provider", default="", help="Provider address (oasyce1...)")
    parser.add_argument("--consumer", default="", help="Consumer address (oasyce1...)")
    args = parser.parse_args()

    client = OasyceClient(args.base_url, timeout=15.0)

    # Health check
    if not client.health():
        print("ERROR: Chain not reachable at", args.base_url)
        sys.exit(1)

    block = client.get_latest_block()
    print(f"Connected to {block.chain_id} at height {block.height}")

    # ----------------------------------------------------------------
    # Step 1: PoW Self-Registration
    # ----------------------------------------------------------------
    step(1, "Solve Proof-of-Work for Self-Registration")

    # In production, an agent would use its own address.
    # Here we demonstrate the PoW solver.
    demo_addr = args.provider or "oasyce1demo_provider_address"
    print(f"  Solving PoW for {demo_addr} (difficulty=16)...")
    pow_result = OasyceClient.solve_pow(demo_addr, difficulty=16)
    print(f"  Solved in {pow_result.attempts} attempts")
    print(f"  Nonce: {pow_result.nonce}")
    print(f"  Hash:  {pow_result.hash_hex[:32]}...")

    # Build the self-register TX (would be signed and broadcast in production)
    tx = client.build_self_register(demo_addr, pow_result.nonce)
    print(f"  TX type: {tx['body']['messages'][0]['@type']}")
    print("  (In production: sign with private key, then client.broadcast_tx(signed_tx))")

    # ----------------------------------------------------------------
    # Step 2: Register AI Capability
    # ----------------------------------------------------------------
    step(2, "Register AI Capability")

    tx = client.build_register_capability(
        sender=demo_addr,
        name="Translation API v2",
        endpoint="https://api.example.com/translate",
        price_uoas=500_000,  # 0.5 OAS per call
        tags=["nlp", "translation", "multi-language"],
        description="Real-time translation across 50+ languages",
    )
    print(f"  Capability: {tx['body']['messages'][0]['name']}")
    print(f"  Price: {tx['body']['messages'][0]['price_per_call']['amount']} uoas")
    print(f"  Tags: {tx['body']['messages'][0]['tags']}")

    # ----------------------------------------------------------------
    # Step 3: Invoke Capability (consumer side)
    # ----------------------------------------------------------------
    step(3, "Invoke Capability (Consumer)")

    consumer_addr = args.consumer or "oasyce1demo_consumer_address"
    tx = client.build_invoke_capability(
        sender=consumer_addr,
        capability_id="CAP_0000000000000001",  # would come from list_capabilities()
        input_data=b'{"text":"hello world","target":"zh"}',
    )
    print(f"  Consumer: {consumer_addr}")
    print(f"  Input: hello world -> zh")
    print("  (Chain auto-creates escrow, locks consumer payment)")

    # ----------------------------------------------------------------
    # Step 4: Complete Invocation (provider submits output)
    # ----------------------------------------------------------------
    step(4, "Complete Invocation (Challenge Window Starts)")

    output_hash = hashlib.sha256('{"translation":"hello world in Chinese"}'.encode()).hexdigest()
    tx = client.build_complete_invocation(
        sender=demo_addr,
        invocation_id="INV_0000000000000001",
        output_hash=output_hash,
        usage_report='{"prompt_tokens":12,"completion_tokens":8}',
    )
    print(f"  Output hash: {output_hash[:32]}...")
    print(f"  Usage report: prompt=12, completion=8 tokens")
    print("  Challenge window: 100 blocks (~8 minutes)")
    print("  Consumer can dispute within this window")

    # ----------------------------------------------------------------
    # Step 5: Claim Payment (after challenge window)
    # ----------------------------------------------------------------
    step(5, "Claim Payment (After Challenge Window)")

    tx = client.build_claim_invocation(
        sender=demo_addr,
        invocation_id="INV_0000000000000001",
    )
    print("  Provider claims payment")
    print("  Escrow releases: 90% provider, 5% protocol, 2% burn, 3% treasury")

    # ----------------------------------------------------------------
    # Step 6: Submit Feedback
    # ----------------------------------------------------------------
    step(6, "Submit Feedback (Consumer)")

    tx = client.build_submit_feedback(
        sender=consumer_addr,
        invocation_id="INV_0000000000000001",
        rating=450,  # 0-500 scale
        comment="Fast and accurate translation",
    )
    print(f"  Rating: 450/500")
    print(f"  Comment: Fast and accurate translation")
    print("  Score decays with 30-day half-life")

    # ----------------------------------------------------------------
    # Step 7: Data Asset Lifecycle
    # ----------------------------------------------------------------
    step(7, "Register Data Asset + Bonding Curve Trading")

    tx = client.build_register_asset(
        sender=demo_addr,
        name="Medical Imaging Dataset v1",
        content_hash=hashlib.sha256(b"medical-imaging-2026").hexdigest(),
        tags=["medical", "imaging", "radiology"],
        description="10K annotated X-ray images for AI training",
    )
    print(f"  Asset: Medical Imaging Dataset v1")
    print(f"  Content hash: {tx['body']['messages'][0]['content_hash'][:32]}...")

    # Buy shares
    tx = client.build_buy_shares(
        sender=consumer_addr,
        asset_id="DATA_0000000000000001",
        amount_uoas=1_000_000,  # 1 OAS
    )
    print(f"  Buy: 1 OAS into bonding curve")
    print(f"  Formula: tokens = supply * (sqrt(1 + payment/reserve) - 1)")

    # Sell shares
    tx = client.build_sell_shares(
        sender=consumer_addr,
        asset_id="DATA_0000000000000001",
        shares=50,
    )
    print(f"  Sell: 50 shares back to curve")
    print(f"  Formula: payout = reserve * (1 - (1-shares/supply)^2), 95% cap")

    # ----------------------------------------------------------------
    # Step 8: Query Everything
    # ----------------------------------------------------------------
    step(8, "Query Chain State (Live Queries)")

    try:
        # These will work against a running chain
        caps = client.list_capabilities()
        print(f"  Capabilities: {len(caps)} registered")

        assets = client.list_assets()
        print(f"  Data assets: {len(assets)} registered")

        leaderboard = client.get_leaderboard()
        print(f"  Reputation: {len(leaderboard)} scored addresses")

        balance = client.get_balance(demo_addr)
        print(f"  Balance: {balance.amount_oas} OAS")
    except Exception as e:
        print(f"  (Queries skipped — chain may not have test data: {e})")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Lifecycle Complete")
    print(f"{'='*60}")
    print()
    print("  SDK coverage:")
    print(f"    27 TX builders (all 7 modules)")
    print(f"    35 query methods")
    print(f"    PoW solver (pure Python, matches Go chain)")
    print(f"    67 total public methods")
    print()
    print("  Next: sign TXs offline, broadcast via client.broadcast_tx()")
    print("  Docs: https://github.com/Shangri-la-0428/oasyce-chain")


if __name__ == "__main__":
    main()
