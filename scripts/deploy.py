"""Pre-tested deployment gate.

    python scripts/deploy.py            # test -> report -> start the app only if every test passed
    python scripts/deploy.py --no-start # just produce the reports (CI)

Writes reports/test_report.html (pytest-html) and reports/TEST_SUMMARY.md (scenario table for judges).
Deployment is refused if any test fails.
"""
from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"

SCENARIOS = [  # (test name prefix, scenario, loop bound / control exercised)
    ("test_01_", "Valid invoice reaches human approval", "Success gate"),
    ("test_02_", "Missing required field is blocked (bad input)", "Failure path"),
    ("test_03_", "Arithmetic mismatch, high confidence: escalate, no pointless retry", "Escalation condition"),
    ("test_04_", "Exact duplicate invoice blocked", "Failure path"),
    ("test_04b_", "Same file uploaded twice blocked", "Failure path"),
    ("test_04c_", "Near-duplicate flagged for the human, not rejected", "Escalation input"),
    ("test_04d_", "Sequential invoice is not a false duplicate", "Precision"),
    ("test_05_", "Invoice above Rs 5,00,000 blocked", "Budget limit"),
    ("test_06_", "Low-confidence failures stop after 3 attempts", "Max iterations"),
    ("test_07_", "Unchanged state hash stops retries", "No-op condition"),
    ("test_08_", "Manager rejection stored in DB + audit", "Human approval"),
    ("test_09_", "Prompt injection cannot approve", "Escalation condition"),
    ("test_high_risk", "High fraud-risk invoice escalated", "Escalation condition"),
    ("test_double_financing", "Same invoice registered by another organisation on chain", "Escalation condition"),
    ("test_crash_and_resume", "App crash while awaiting approval, then resume", "Checkpointing"),
    ("test_uploader_cannot_approve", "Uploader cannot approve own invoice", "Separation of duties"),
    ("test_manager_approval_limit", "Manager approval limit enforced", "Budget limit"),
    ("test_field_correction", "Correction re-runs validation + checker; maker-checker", "Human approval"),
    ("test_chain_down", "Blockchain unavailable does not block the workflow", "Resilience"),
    ("test_audit_chain_detects", "Tampered audit log is detected", "Audit"),
]


def run_tests() -> tuple[int, Path]:
    REPORTS.mkdir(exist_ok=True)
    junit = REPORTS / "junit.xml"
    cmd = [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}",
           f"--html={REPORTS / 'test_report.html'}", "--self-contained-html"]
    print("Running pre-deployment tests:", " ".join(cmd[2:]))
    return subprocess.call(cmd, cwd=ROOT), junit


def summarise(junit: Path) -> tuple[int, int, int]:
    results = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        outcome = "FAIL" if case.find("failure") is not None or case.find("error") is not None else \
            "SKIP" if case.find("skipped") is not None else "PASS"
        results[case.get("name")] = (outcome, float(case.get("time", 0)))
    passed = sum(1 for o, _ in results.values() if o == "PASS")
    failed = sum(1 for o, _ in results.values() if o == "FAIL")
    skipped = sum(1 for o, _ in results.values() if o == "SKIP")

    lines = [f"# InvoiceGuard AI - pre-deployment test summary",
             f"", f"Generated {datetime.now():%Y-%m-%d %H:%M}. **{passed} passed, {failed} failed, {skipped} skipped** "
             f"of {len(results)} tests. Deployment is {'ALLOWED' if not failed else '**REFUSED**'}.", "",
             "| Scenario | Bound / control | Result |", "|---|---|---|"]
    for prefix, scenario, bound in SCENARIOS:
        hits = [o for name, (o, _) in results.items() if name.startswith(prefix)]
        verdict = "not run" if not hits else "FAIL" if "FAIL" in hits else "SKIP" if "SKIP" in hits else "PASS"
        lines.append(f"| {scenario} | {bound} | {verdict} |")
    lines += ["", "Full per-test detail: `reports/test_report.html`."]
    (REPORTS / "TEST_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return passed, failed, skipped


def main() -> int:
    code, junit = run_tests()
    passed, failed, skipped = summarise(junit)
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped -> reports/TEST_SUMMARY.md")
    if code != 0 or failed:
        print("DEPLOYMENT REFUSED: fix the failing tests first.")
        return 1
    if "--no-start" in sys.argv:
        return 0
    print("All tests passed. Starting InvoiceGuard AI (UI on :8501, API on :8000)...")
    env = {**os.environ, "INVOICEGUARD_API_PORT": os.environ.get("INVOICEGUARD_API_PORT", "8000")}
    return subprocess.call([sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py"], cwd=ROOT, env=env)


if __name__ == "__main__":
    sys.exit(main())
