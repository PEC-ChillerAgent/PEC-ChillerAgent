"""Public Python entry point for stage-one dataset and tool operations."""

from pathlib import Path

from chiller_app.api.workbench import WorkbenchSchema
from energy_agent.config.settings import default_data_dir
from energy_agent.contracts.datasets import DatasetCreate, DatasetInfo
from energy_agent.contracts.tools import ChillerAnalysisRequest, ToolResult
from energy_agent.registry.tools import ToolRegistry
from energy_agent.storage.repository import Repository
from energy_agent.tools.chiller.backend import run_model
from energy_agent.tools.chiller.tool import ChillerTool


class AgentRuntime:
    def __init__(self, data_dir: str | Path | None = None):
        self.repository = Repository(data_dir if data_dir is not None else default_data_dir())
        self.registry = ToolRegistry()
        self.registry.register(ChillerTool(self.repository))

    def register_dataset(self, request: DatasetCreate | dict) -> DatasetInfo:
        request = request if isinstance(request, DatasetCreate) else DatasetCreate.model_validate(request)
        checked = run_model({"operation": "calculate", "records": request.records, "schema": request.data_schema.model_dump()})
        return self.repository.create_dataset(
            request, effective_schema=WorkbenchSchema.model_validate(checked["metadata"]["schema"]),
            quality={"invalid_measurement_count": len(checked["issues"]),
                     "input_inference": checked["metadata"].get("input_inference", {}),
                     "source_order_preserved": True},
        )

    def analyze(self, request: ChillerAnalysisRequest | dict) -> ToolResult:
        return self.registry.execute("chiller_analyze", request)
