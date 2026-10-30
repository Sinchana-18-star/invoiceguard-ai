"""Shared invoice ledger on an EVM blockchain (contract: blockchain/InvoiceRegistry.sol).

Why a blockchain here: one company's database cannot see that a supplier sent the *same* invoice to
another company or lender (double payment / double financing). A shared registry of invoice
fingerprints can, without exposing invoice data - only SHA-256(salt | GSTIN | invoice number) goes on chain.

Modes (INVOICEGUARD_LEDGER):
  local (default) - a local Hardhat node on 127.0.0.1:8545 (started automatically from blockchain/ if it is
                    not running). Hardhat keeps the chain in memory, so when the chain was reset the app
                    redeploys the contract and re-anchors its own records from the database.
  rpc             - any EVM JSON-RPC node, e.g. Polygon Amoy testnet: INVOICEGUARD_CHAIN_RPC,
                    INVOICEGUARD_CHAIN_KEY (private key; optional for unlocked dev nodes),
                    INVOICEGUARD_CHAIN_CONTRACT (optional existing contract address).
  off             - disabled.
The ledger never blocks the workflow: if the chain is unavailable the step is logged and skipped.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from core.config import ROOT

ARTIFACT = ROOT / "blockchain" / "InvoiceRegistry.json"
STATUS_NAMES = {0: "NONE", 1: "REGISTERED", 2: "APPROVED", 3: "REJECTED"}
DEFAULT_LOCAL_RPC = "http://127.0.0.1:8545"
_local_node: subprocess.Popen | None = None


def start_local_node(rpc_url: str, wait_seconds: int = 45) -> None:
    """Start `npx hardhat node` from blockchain/ and wait until it answers."""
    global _local_node
    from web3 import Web3

    port = rpc_url.rsplit(":", 1)[-1].strip("/")
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx or not (ROOT / "blockchain" / "node_modules" / "hardhat").exists():
        raise RuntimeError("Hardhat not installed: run `npm install` in blockchain/")
    log = open(ROOT / "blockchain" / "hardhat-node.log", "ab")
    _local_node = subprocess.Popen([npx, "hardhat", "node", "--hostname", "127.0.0.1", "--port", port],
                                   cwd=ROOT / "blockchain", stdout=log, stderr=subprocess.STDOUT)
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 2}))
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if w3.is_connected():
            return
        if _local_node.poll() is not None:
            raise RuntimeError("Hardhat node exited; see blockchain/hardhat-node.log")
        time.sleep(0.5)
    raise TimeoutError("Hardhat node did not start in time")


def invoice_key(gstin: str, invoice_number: str) -> bytes:
    salt = os.environ.get("INVOICEGUARD_LEDGER_SALT", "invoiceguard-consortium-v1")
    norm = "".join((invoice_number or "").upper().split())
    return hashlib.sha256(f"{salt}|{(gstin or '').upper()}|{norm}".encode()).digest()


class Ledger:
    def __init__(self, w3, contract, account: str, private_key: str | None = None, mode: str = "local"):
        self.w3, self.contract, self.account, self._key, self.mode = w3, contract, account, private_key, mode
        self.fresh_contract = False  # True when the contract was (re)deployed during this start-up
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_env(cls, data_dir: Path) -> "Ledger | None":
        mode = os.environ.get("INVOICEGUARD_LEDGER", "local").lower()
        if mode == "off":
            return None
        from web3 import Web3

        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        rpc_url = os.environ.get("INVOICEGUARD_CHAIN_RPC") or (DEFAULT_LOCAL_RPC if mode == "local" else None)
        if not rpc_url:
            raise ValueError("INVOICEGUARD_CHAIN_RPC is required in rpc mode")
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        if not w3.is_connected():
            if mode != "local":
                raise ConnectionError(f"Cannot reach blockchain node at {rpc_url}")
            start_local_node(rpc_url)
        key = os.environ.get("INVOICEGUARD_CHAIN_KEY")
        account = w3.eth.account.from_key(key).address if key else w3.eth.accounts[0]
        ledger = cls(w3, None, account, key, mode)

        store = data_dir / "ledger.json"
        known = json.loads(store.read_text()) if store.exists() else {}
        address = os.environ.get("INVOICEGUARD_CHAIN_CONTRACT") or known.get(str(w3.eth.chain_id))
        if not address or len(w3.eth.get_code(address)) == 0:  # never deployed, or the dev chain was reset
            address = ledger._deploy(artifact)
            ledger.fresh_contract = True
            known[str(w3.eth.chain_id)] = address
            store.write_text(json.dumps(known, indent=2))
        ledger.contract = w3.eth.contract(address=address, abi=artifact["abi"])
        return ledger

    def as_organisation(self, index: int) -> "Ledger":
        """Another organisation on the same dev chain (unlocked Hardhat account) - demo and tests only."""
        return Ledger(self.w3, self.contract, self.w3.eth.accounts[index], None, self.mode)

    # ------------------------------------------------------------------ transactions
    def _send(self, fn) -> dict:
        with self._lock:
            if self._key:
                tx = fn.build_transaction({"from": self.account, "chainId": self.w3.eth.chain_id,
                                           "nonce": self.w3.eth.get_transaction_count(self.account)})
                signed = self.w3.eth.account.sign_transaction(tx, self._key)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            else:
                tx_hash = fn.transact({"from": self.account})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        return {"tx_hash": self.w3.to_hex(receipt.transactionHash), "block": receipt.blockNumber}

    def _deploy(self, artifact: dict) -> str:
        factory = self.w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        with self._lock:
            if self._key:
                tx = factory.constructor().build_transaction({
                    "from": self.account, "chainId": self.w3.eth.chain_id,
                    "nonce": self.w3.eth.get_transaction_count(self.account)})
                tx_hash = self.w3.eth.send_raw_transaction(self.w3.eth.account.sign_transaction(tx, self._key).raw_transaction)
            else:
                tx_hash = factory.constructor().transact({"from": self.account})
            return self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120).contractAddress

    # ------------------------------------------------------------------ API used by the workflow
    def info(self) -> dict:
        return {"mode": self.mode, "chain_id": self.w3.eth.chain_id, "contract": self.contract.address,
                "account": self.account, "total_registered": self.contract.functions.totalRegistered().call(),
                "block": self.w3.eth.block_number}

    def lookup(self, key: bytes) -> dict:
        registrar, registered_at, status, decision = self.contract.functions.lookup(key).call()
        return {"registrar": registrar, "registered_at": registered_at, "status": STATUS_NAMES.get(status, status),
                "decision_hash": decision.hex()}

    def register(self, gstin: str, invoice_number: str) -> dict:
        key = invoice_key(gstin, invoice_number)
        base = {"invoice_key": key.hex(), "contract": self.contract.address, "chain_id": self.w3.eth.chain_id,
                "mode": self.mode}
        existing = self.lookup(key)
        if existing["registrar"] == self.account:
            return {**base, "status": "ALREADY_OURS", "on_chain_status": existing["status"]}
        if int(existing["registrar"], 16) != 0:
            return {**base, "status": "REGISTERED_ELSEWHERE", "registrar": existing["registrar"],
                    "on_chain_status": existing["status"]}
        return {**base, "status": "REGISTERED", **self._send(self.contract.functions.registerInvoice(key))}

    def record_decision(self, key_hex: str, approved: bool, decision_hash: bytes) -> dict:
        return self._send(self.contract.functions.recordDecision(bytes.fromhex(key_hex), approved, decision_hash))
