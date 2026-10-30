"""Blockchain invoice registry (InvoiceRegistry.sol deployed on a real local Hardhat EVM node)."""
from __future__ import annotations

import socket

import pytest

pytest.importorskip("web3")

from conftest import ROOT, FakeStrategy, events, result_from, submit, valid_intra_fields  # noqa: E402
from core import ledger as ledger_mod  # noqa: E402
from core import service  # noqa: E402
from core.db import Status  # noqa: E402
from core.demo_data import SUPPLIER_A_GSTIN  # noqa: E402
from core.ledger import invoice_key  # noqa: E402

if not (ROOT / "blockchain" / "node_modules" / "hardhat").exists():
    pytest.skip("Hardhat not installed (cd blockchain && npm install)", allow_module_level=True)


@pytest.fixture(scope="module")
def hardhat_rpc():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    ledger_mod.start_local_node(url, wait_seconds=90)
    node = ledger_mod._local_node
    yield url
    node.terminate()


@pytest.fixture
def chain_ctx(make_ctx, monkeypatch, hardhat_rpc):
    monkeypatch.setenv("INVOICEGUARD_LEDGER", "local")
    monkeypatch.setenv("INVOICEGUARD_CHAIN_RPC", hardhat_rpc)

    def _make(fields=None, **kw):
        ctx = make_ctx({"fake": FakeStrategy(result_from(fields or valid_intra_fields()))}, **kw)
        assert ctx.ledger is not None, ctx.ledger_error
        return ctx
    return _make


def test_invoice_registered_and_decision_anchored(chain_ctx):
    ctx = chain_ctx()
    inv = submit(ctx)
    assert inv["ledger"]["status"] == "REGISTERED" and inv["ledger"]["tx_hash"]
    assert "LEDGER_REGISTERED" in events(ctx, inv["id"])
    service.decide(ctx, inv["id"], "mgr_priya", "approve")
    on_chain = ctx.ledger.lookup(invoice_key(SUPPLIER_A_GSTIN, "DSW-T-0001"))
    assert on_chain["registrar"] == ctx.ledger.account and on_chain["status"] == "APPROVED"
    assert int(on_chain["decision_hash"], 16) != 0
    assert "LEDGER_DECISION_RECORDED" in events(ctx, inv["id"])


def test_only_hash_goes_on_chain():
    key = invoice_key(SUPPLIER_A_GSTIN, "DSW-T-0001")
    assert len(key) == 32 and SUPPLIER_A_GSTIN.encode() not in key
    assert key == invoice_key(SUPPLIER_A_GSTIN.lower(), " dsw-t-0001 ")  # normalised before hashing


def test_double_financing_detected_across_organisations(chain_ctx):
    ctx = chain_ctx()
    other = service.simulate_other_organisation_registration(ctx, SUPPLIER_A_GSTIN, "DSW-T-0001")
    assert other["status"] == "REGISTERED"
    inv = submit(ctx)
    assert inv["ledger"]["status"] == "REGISTERED_ELSEWHERE"
    assert "DOUBLE_FINANCING_SUSPECTED" in inv["flags"]
    assert inv["checker"]["passed"] is True                      # arithmetic is fine...
    assert inv["status"] == Status.ESCALATED                      # ...but it must not reach approval
    assert inv["escalation_reason"].startswith("FRAUD_RISK_HIGH")
    assert "DOUBLE_FINANCING" in {s["code"] for s in inv["checker"]["risk"]["signals"]}


def test_reprocessing_own_invoice_is_not_a_duplicate(chain_ctx):
    ctx = chain_ctx(valid_intra_fields(grand_total="4100.00"))
    inv = submit(ctx)
    assert inv["status"] == Status.ESCALATED
    fixed = service.decide(ctx, inv["id"], "mgr_priya", "correct", corrections={"grand_total": "3894.00"})
    assert fixed["status"] == Status.AWAITING_APPROVAL
    assert fixed["ledger"]["status"] == "ALREADY_OURS"


def test_app_restart_reuses_contract(chain_ctx, tmp_path):
    ctx = chain_ctx(data_dir=tmp_path / "persist")
    submit(ctx)
    address = ctx.ledger.contract.address
    ctx.close()
    restarted = chain_ctx(data_dir=tmp_path / "persist")
    assert restarted.ledger.contract.address == address and not restarted.ledger.fresh_contract


def test_reset_dev_chain_is_reanchored(chain_ctx, tmp_path):
    ctx = chain_ctx(data_dir=tmp_path / "persist")
    inv = submit(ctx)
    service.decide(ctx, inv["id"], "mgr_priya", "reject", reason="Wrong delivery address")
    ctx.ledger.w3.provider.make_request("hardhat_reset", [])  # the in-memory dev chain is wiped
    ctx.close()
    restarted = chain_ctx(data_dir=tmp_path / "persist")
    assert restarted.ledger.fresh_contract
    on_chain = restarted.ledger.lookup(invoice_key(SUPPLIER_A_GSTIN, "DSW-T-0001"))
    assert on_chain["registrar"] == restarted.ledger.account and on_chain["status"] == "REJECTED"


def test_chain_down_does_not_block_workflow(make_ctx, monkeypatch, hardhat_rpc):
    monkeypatch.setenv("INVOICEGUARD_LEDGER", "rpc")
    monkeypatch.setenv("INVOICEGUARD_CHAIN_RPC", "http://127.0.0.1:9")  # nothing listens here
    ctx = make_ctx({"fake": FakeStrategy(result_from(valid_intra_fields()))})
    assert ctx.ledger is None and ctx.ledger_error
    inv = submit(ctx)
    assert inv["status"] == Status.AWAITING_APPROVAL
    assert inv["ledger"]["status"] == "DISABLED"
