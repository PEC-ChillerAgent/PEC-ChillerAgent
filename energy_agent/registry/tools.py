"""Explicit equipment tool registry with discoverable JSON contracts."""

from energy_agent.contracts.tools import ChillerAnalysisRequest, ToolResult
from energy_agent.storage.repository import ReferenceNotFound


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self) -> list[dict]:
        return [{"name": name, "version": "1.0.0", "equipment_type": "chiller",
                 "description": "Calculate measured chiller physics, simulate ElectricEIR, or compare aligned measurements with model outputs. No training, calibration or control.",
                 "tasks": ["physics", "simulate", "compare"],
                 "input_schema": ChillerAnalysisRequest.model_json_schema(),
                 "output_schema": ToolResult.model_json_schema()}
                for name in self._tools]

    def execute(self, name: str, arguments: dict | ChillerAnalysisRequest) -> ToolResult:
        if name not in self._tools:
            raise ReferenceNotFound(f"Tool not found: {name}")
        request = arguments if isinstance(arguments, ChillerAnalysisRequest) else ChillerAnalysisRequest.model_validate(arguments)
        return self._tools[name].execute(request)
