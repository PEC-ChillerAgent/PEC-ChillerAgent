"""Declarative definition of the supported ElectricEIR simulation model."""

from __future__ import annotations

from typing import Any

from .electric_eir import eir_model_definition


def default_model_definition() -> dict[str, Any]:
    return eir_model_definition()
