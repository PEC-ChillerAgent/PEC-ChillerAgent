"""Build the bundled ElectricEIR catalogue from an installed Buildings source.

Usage: python -m chiller_app.model.import_buildings_eir <Buildings-directory>
Only numeric literals, +, - and * are accepted; Modelica code is never executed.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys


def number(expression: str) -> float:
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, right = visit(node.left), visit(node.right)
            return left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
        raise ValueError(f"Unsupported numeric expression: {expression}")
    return visit(ast.parse(expression.strip(), mode="eval").body)


def import_catalogue(root: Path) -> dict:
    relative = "Fluid/Chillers/Data/ElectricEIR.mo"
    source = (root / relative).read_text(encoding="utf-8")
    records = []
    pattern = r'record\s+(\w+)\s*=\s*Buildings\.Fluid\.Chillers\.Data\.ElectricEIR\.Generic\s*\((.*?)\)\s*"([^"]*)"'
    for name, body, description in re.findall(pattern, source, re.S):
        parameters = {}
        for key, value in re.findall(r'(\w+)\s*=\s*(\{[^}]*\}|[^,\n]+)', body):
            parameters[key] = [number(v) for v in value[1:-1].split(",")] if value.startswith("{") else number(value)
        records.append({"id": name, "description": description,
                        "condenser_medium": "air" if "AirCooled" in name else "water",
                        "parameters": parameters})
    if not records:
        raise ValueError("No ElectricEIR records found")
    paths = [relative, "Fluid/Chillers/ElectricEIR.mo", "Fluid/Chillers/BaseClasses/PartialElectric.mo",
             "Fluid/Interfaces/FourPortHeatMassExchanger.mo", "Utilities/Math/Functions/biquadratic.mo",
             "Utilities/Math/Functions/smoothMin.mo", "Utilities/Math/Functions/smoothMax.mo",
             "Utilities/Math/Functions/regStep.mo", "Media/Water.mo", "UsersGuide/License.mo"]
    return {"library": "Buildings", "version": "13.0.0", "source": relative,
            "source_sha256": {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
            "records": records}


if __name__ == "__main__":
    catalogue = import_catalogue(Path(sys.argv[1]))
    target = Path(__file__).with_name("buildings_eir_catalogue.json")
    target.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(catalogue['records'])} records to {target}")
