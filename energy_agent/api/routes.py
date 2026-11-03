"""HTTP access to datasets and deterministic tools; no conversation endpoint."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import JsonValue, ValidationError

from chiller_app.api.workbench import eir_catalogue, upload
from energy_agent.contracts.datasets import DatasetCreate, DatasetInfo
from energy_agent.contracts.tools import ToolResult
from energy_agent.runtime import AgentRuntime
from energy_agent.storage.repository import ReferenceNotFound
from energy_agent.tools.chiller.tool import AssetMismatch

router = APIRouter(prefix="/agent/v1", tags=["设备分析工具 · 第一阶段"])


def runtime(request: Request) -> AgentRuntime:
    instance = getattr(request.app.state, "energy_runtime", None)
    if instance is None:
        instance = AgentRuntime(getattr(request.app.state, "energy_data_dir", None))
        request.app.state.energy_runtime = instance
    return instance


def call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ReferenceNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except AssetMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "stage": 1, "service": "energy-equipment-tools"}


@router.get("/tools")
def tools(instance: AgentRuntime = Depends(runtime)) -> dict:
    return {"tools": instance.registry.definitions()}


@router.get("/models/chiller")
def models() -> dict:
    return eir_catalogue()


@router.post("/datasets", response_model=DatasetInfo, status_code=201)
def create_dataset(request: DatasetCreate, instance: AgentRuntime = Depends(runtime)):
    return call(instance.register_dataset, request)


@router.post("/datasets/upload", response_model=DatasetInfo, status_code=201)
async def upload_dataset(
    asset_id: str = Form(...), schema_text: str = Form(..., alias="schema"),
    file: UploadFile = File(...), sheet_name: str | None = Form(None),
    instance: AgentRuntime = Depends(runtime),
):
    parsed = await upload(file, sheet_name=sheet_name)
    def register():
        return instance.register_dataset(DatasetCreate.model_validate({
            "asset_id": asset_id, "records": parsed["records"], "schema": json.loads(schema_text),
            "source": {"kind": "upload", "name": parsed["filename"], "sheet": parsed["selected_sheet"]},
        }))
    return call(register)


@router.get("/datasets", response_model=list[DatasetInfo])
def datasets(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
             instance: AgentRuntime = Depends(runtime)):
    return instance.repository.list_datasets(offset=offset, limit=limit)


@router.get("/datasets/{dataset_id}", response_model=DatasetInfo)
def dataset(dataset_id: str, instance: AgentRuntime = Depends(runtime)):
    return call(instance.repository.get_dataset, dataset_id).info


@router.get("/datasets/{dataset_id}/records")
def dataset_records(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
                    instance: AgentRuntime = Depends(runtime)):
    snapshot = call(instance.repository.get_dataset, dataset_id)
    return {"dataset_id": dataset_id, "total": len(snapshot.records), "offset": offset,
            "limit": limit, "records": snapshot.records[offset:offset + limit]}


@router.post("/tools/{tool_name}/execute", response_model=ToolResult)
def execute(tool_name: str, arguments: dict[str, JsonValue], instance: AgentRuntime = Depends(runtime)):
    return call(instance.registry.execute, tool_name, arguments)


@router.get("/runs/{run_id}", response_model=ToolResult)
def run(run_id: str, instance: AgentRuntime = Depends(runtime)):
    return call(instance.repository.get_run, run_id)["result"]


@router.get("/runs/{run_id}/records")
def run_records(run_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
                instance: AgentRuntime = Depends(runtime)):
    artifact = call(instance.repository.get_run, run_id)
    records = artifact["model_output"]["records"]
    return {"run_id": run_id, "total": len(records), "offset": offset,
            "limit": limit, "records": records[offset:offset + limit]}


@router.get("/runs/{run_id}/artifact")
def artifact(run_id: str, instance: AgentRuntime = Depends(runtime)):
    data = call(instance.repository.get_run, run_id)
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{data["result"]["run_id"]}.json"'})
