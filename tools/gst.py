"""Indian GST helpers: GSTIN structure/state-code/checksum validation and tax arithmetic."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (old)", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}

PAISE = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def gstin_checksum(first14: str) -> str:
    """Return the 15th (check) character for the first 14 characters of a GSTIN."""
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARSET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _CHARSET[(36 - total % 36) % 36]


def make_gstin(first14: str) -> str:
    return first14 + gstin_checksum(first14)


def validate_gstin(gstin: str | None) -> list[str]:
    """Return a list of problems; empty list means the GSTIN is valid."""
    if not gstin:
        return ["GSTIN is missing"]
    g = gstin.strip().upper()
    if not GSTIN_RE.match(g):
        return [f"GSTIN '{g}' does not match the 15-character GSTIN structure"]
    errors = []
    if g[:2] not in STATE_CODES:
        errors.append(f"GSTIN state code '{g[:2]}' is not a valid Indian state code")
    expected = gstin_checksum(g[:14])
    if g[14] != expected:
        errors.append(f"GSTIN checksum character is '{g[14]}', expected '{expected}'")
    return errors


def state_code(gstin: str | None) -> str | None:
    if gstin and len(gstin) >= 2 and gstin[:2].isdigit():
        return gstin[:2]
    return None


def expected_tax_split(taxable: Decimal, rate: Decimal, intra_state: bool) -> dict[str, Decimal]:
    """Tax due on one line. Intra-state: CGST + SGST (half each). Inter-state: IGST."""
    tax = taxable * rate / Decimal(100)
    if intra_state:
        half = tax / 2
        return {"cgst": half, "sgst": half, "igst": Decimal(0)}
    return {"cgst": Decimal(0), "sgst": Decimal(0), "igst": tax}
