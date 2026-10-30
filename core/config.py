"""Workflow specification loading (workflow_spec.yaml) validated with Pydantic."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tools.gst import validate_gstin

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC_PATH = ROOT / "workflow_spec.yaml"


class Bounds(BaseModel):
    max_iterations: int = Field(ge=1, le=10)
    max_tool_calls: int = Field(ge=1, le=100)
    timeout_seconds: int = Field(ge=1)
    no_op_rule: Literal["escalate_if_state_hash_unchanged"]
    max_invoice_value_inr: Decimal = Field(gt=0)


class Thresholds(BaseModel):
    low_confidence: float = Field(ge=0, le=1)
    green_confidence: float = Field(ge=0, le=1)
    amber_confidence: float = Field(ge=0, le=1)
    rounding_tolerance_inr: Decimal = Field(ge=0)
    price_tolerance_pct: Decimal = Field(ge=0)
    fuzzy_duplicate_days: int = Field(ge=0)
    fuzzy_invoice_number_distance: int = Field(ge=0)
    fuzzy_amount_tolerance_pct: Decimal = Field(ge=0)


class GSTConfig(BaseModel):
    valid_rates: list[Decimal]


class Company(BaseModel):
    name: str
    gstin: str

    @field_validator("gstin")
    @classmethod
    def _valid_gstin(cls, v: str) -> str:
        problems = validate_gstin(v)
        if problems:
            raise ValueError("; ".join(problems))
        return v.upper()


class WorkflowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: str
    version: str
    description: str
    approver: str
    inputs: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    outputs: dict[str, Any]
    rules: list[str]
    bounds: Bounds
    success_gate: list[str] = Field(min_length=1)
    escalation_conditions: list[str] = Field(min_length=1)
    extraction_strategies: list[str] = Field(min_length=1)
    thresholds: Thresholds
    gst: GSTConfig
    company: Company


def load_spec(path: Path | str | None = None) -> WorkflowSpec:
    with open(path or DEFAULT_SPEC_PATH, encoding="utf-8") as f:
        return WorkflowSpec.model_validate(yaml.safe_load(f))
