"""DEMO FIXTURES ONLY - clearly fictional users, suppliers, POs and GRNs for the hackathon demo and tests.
None of these are real businesses or records."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from core.db import User
from tools.gst import make_gstin

SUPPLIER_A_GSTIN = make_gstin("29AAACS5678K1Z")  # Karnataka  -> intra-state for our Karnataka buyer
SUPPLIER_B_GSTIN = make_gstin("27AABCP4321M1Z")  # Maharashtra -> inter-state

DEMO_USERS = [
    ("emp_asha", "Asha (Employee, demo)", "employee", None),
    ("emp_ravi", "Ravi (Employee, demo)", "employee", None),
    ("mgr_priya", "Priya (Accounts Manager, demo)", "accounts_manager", Decimal("500000")),
    ("mgr_arjun", "Arjun (Accounts Manager, demo)", "accounts_manager", Decimal("100000")),
    ("aud_meera", "Meera (Auditor, demo)", "auditor", None),
]
DEMO_SUPPLIERS = [
    ("Demo Steel Works Pvt Ltd", SUPPLIER_A_GSTIN),
    ("Demo Motion Systems Pvt Ltd", SUPPLIER_B_GSTIN),
]
DEMO_POS = [
    ("PO-1001", SUPPLIER_A_GSTIN, [
        {"description": "Steel Bolts M8", "quantity": 500, "unit_price": "12.50", "gst_rate": 18},
        {"description": "Hex Nuts M8", "quantity": 500, "unit_price": "4.00", "gst_rate": 18},
        {"description": "Industrial Gloves", "quantity": 100, "unit_price": "85.00", "gst_rate": 12},
    ]),
    ("PO-2001", SUPPLIER_B_GSTIN, [
        {"description": "Servo Motor 750W", "quantity": 10, "unit_price": "18500.00", "gst_rate": 18},
        {"description": "Motor Controller", "quantity": 10, "unit_price": "6200.00", "gst_rate": 18},
    ]),
    ("PO-3001", SUPPLIER_B_GSTIN, [
        {"description": "Industrial Gearbox", "quantity": 30, "unit_price": "15000.00", "gst_rate": 18},
    ]),
]
DEMO_GRNS = [
    ("GRN-1001", "PO-1001", [
        {"description": "Steel Bolts M8", "quantity_received": 400},
        {"description": "Hex Nuts M8", "quantity_received": 400},
        {"description": "Industrial Gloves", "quantity_received": 100},
    ]),
    ("GRN-2001", "PO-2001", [
        {"description": "Servo Motor 750W", "quantity_received": 10},
        {"description": "Motor Controller", "quantity_received": 10},
    ]),
    ("GRN-3001", "PO-3001", [{"description": "Industrial Gearbox", "quantity_received": 30}]),
]


def seed_demo_data(ctx) -> bool:
    """Insert demo fixtures if the database has no users yet. Returns True if it seeded."""
    from core import service

    with ctx.Session() as s:
        if s.scalar(select(User).limit(1)) is not None:
            return False
        for uid, name, role, limit in DEMO_USERS:
            s.add(User(id=uid, name=name, role=role, approval_limit=limit))
        s.commit()
    for name, gstin in DEMO_SUPPLIERS:
        service.add_supplier(ctx, name, gstin)
    for po, gstin, items in DEMO_POS:
        service.add_purchase_order(ctx, po, gstin, items)
    for grn, po, items in DEMO_GRNS:
        service.add_goods_receipt(ctx, grn, po, items)
    ctx.audit.append_event(None, "DEMO_DATA_SEEDED", "system", {"users": len(DEMO_USERS), "suppliers": len(DEMO_SUPPLIERS)})
    return True
