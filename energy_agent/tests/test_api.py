from io import BytesIO
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pandas as pd

from energy_agent.api.app import create_app


def test_http_full_flow_restart_evidence_and_artifact(data_dir, physics_source):
    client = TestClient(create_app(data_dir))
    created = client.post("/agent/v1/datasets", json=physics_source)
    assert created.status_code == 201, created.text
    dataset = created.json()
    response = client.post("/agent/v1/tools/chiller_analyze/execute", json={
        "asset_id": dataset["asset_id"], "dataset_id": dataset["dataset_id"], "task": "physics"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "success"
    assert result["metrics"]["COP"]["value"] == 4.18
    restarted = TestClient(create_app(data_dir))
    assert restarted.get(f'/agent/v1/runs/{result["run_id"]}').json() == result
    records = restarted.get(f'/agent/v1/runs/{result["run_id"]}/records').json()
    assert records["records"][0]["cooling_capacity_kW"] == 418
    artifact = restarted.get(f'/agent/v1/runs/{result["run_id"]}/artifact')
    assert "attachment" in artifact.headers["content-disposition"]
    assert artifact.json()["result"] == result
    assert restarted.get(f'/agent/v1/datasets/{dataset["dataset_id"]}').json()["version"] == 1
    assert restarted.get(f'/agent/v1/datasets/{dataset["dataset_id"]}/records').json()["total"] == 1
    assert len(restarted.get("/agent/v1/datasets").json()) == 1
    assert restarted.get("/agent/v1/tools").json()["tools"][0]["name"] == "chiller_analyze"
    assert len(restarted.get("/agent/v1/models/chiller").json()["records"]) == 158


def test_api_reference_validation_pagination_and_asset_boundary(data_dir, physics_source):
    client = TestClient(create_app(data_dir))
    for route in ("/agent/v1/datasets/missing", "/agent/v1/runs/missing"):
        assert client.get(route).status_code == 404
    dataset = client.post("/agent/v1/datasets", json=physics_source).json()
    arguments = {"asset_id": "wrong", "dataset_id": dataset["dataset_id"]}
    assert client.post("/agent/v1/tools/chiller_analyze/execute", json=arguments).status_code == 409
    arguments["asset_id"] = dataset["asset_id"]
    assert client.post("/agent/v1/tools/unknown/execute", json=arguments).status_code == 404
    assert client.post("/agent/v1/tools/chiller_analyze/execute", json={**arguments, "task": "train"}).status_code == 422
    assert client.get(f'/agent/v1/datasets/{dataset["dataset_id"]}/records?limit=1001').status_code == 422
    assert client.get(f'/agent/v1/datasets/{dataset["dataset_id"]}/records?offset=-1').status_code == 422
    assert client.get(f'/agent/v1/datasets/{dataset["dataset_id"]}/records?offset=1').json()["records"] == []


def test_upload_csv_and_selected_excel_sheet(data_dir, physics_source):
    client = TestClient(create_app(data_dir))
    frame = pd.DataFrame(physics_source["records"])
    body = {"asset_id": "chiller_01", "schema": json.dumps(physics_source["schema"])}
    response = client.post("/agent/v1/datasets/upload", data=body,
                           files={"file": ("measurements.csv", frame.to_csv(index=False).encode("utf-8"))})
    assert response.status_code == 201, response.text
    assert response.json()["source"]["name"] == "measurements.csv"
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.assign(tei=99).to_excel(writer, sheet_name="unused", index=False)
        frame.to_excel(writer, sheet_name="selected", index=False)
    response = client.post("/agent/v1/datasets/upload", data={**body, "sheet_name": "selected"},
                           files={"file": ("source.xlsx", buffer.getvalue())})
    assert response.status_code == 201, response.text
    assert response.json()["source"]["sheet"] == "selected"
    dataset_id = response.json()["dataset_id"]
    assert client.get(f"/agent/v1/datasets/{dataset_id}/records").json()["records"][0]["tei"] == 10
    bad = client.post("/agent/v1/datasets/upload", data={**body, "schema": "{"},
                      files={"file": ("measurements.csv", frame.to_csv(index=False).encode())})
    assert bad.status_code == 422


def test_routes_are_available_on_existing_application(data_dir):
    from chiller_app.api.fastapi_app import app
    from energy_agent.api.routes import runtime
    from energy_agent.runtime import AgentRuntime
    app.dependency_overrides[runtime] = lambda: AgentRuntime(data_dir)
    try:
        client = TestClient(app)
        assert client.get("/").status_code == 200
        assert client.get("/agent/v1/health").json()["stage"] == 1
        assert client.get("/agent/v1/tools").status_code == 200
    finally:
        app.dependency_overrides.pop(runtime)


def test_cli_dataset_analyze_and_export(data_dir, physics_source):
    root = Path(__file__).resolve().parents[2]
    request = data_dir / "dataset.json"
    request.write_text(json.dumps(physics_source), encoding="utf-8")
    def cli(*args):
        result = subprocess.run([sys.executable, "-B", "-m", "energy_agent", "--data-dir", str(data_dir), *args],
                                cwd=root, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    dataset = cli("dataset-create", "--request", str(request))
    request.write_text(json.dumps({"asset_id": dataset["asset_id"], "dataset_id": dataset["dataset_id"]}), encoding="utf-8")
    result = cli("analyze", "--request", str(request))
    assert result["metrics"]["COP"]["value"] == 4.18
    artifact = cli("run-export", "--id", result["run_id"])
    assert artifact["result"] == result
    assert artifact["model_output"]["records"][0]["cooling_capacity_kW"] == 418


def test_existing_saved_row_field_names_remain_queryable(data_dir, physics_source):
    from energy_agent.runtime import AgentRuntime
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(physics_source)
    result = runtime.analyze({"asset_id": dataset.asset_id, "dataset_id": dataset.dataset_id})
    original = runtime.repository.get_run(result.run_id)
    saved = original["result"]
    def old_names(value):
        if isinstance(value, dict):
            return {key.replace("source_row_examples", "source_rows"): old_names(item) for key, item in value.items()}
        if isinstance(value, list):
            return [old_names(item) for item in value]
        return value
    legacy = old_names(saved)
    import sqlite3
    with closing(sqlite3.connect(runtime.repository.path)) as db, db:
        db.execute("UPDATE runs SET result = ? WHERE id = ?", (json.dumps(legacy), result.run_id))
    client = TestClient(create_app(data_dir))
    response = client.get(f"/agent/v1/runs/{result.run_id}")
    assert response.status_code == 200, response.text
    assert response.json() == saved
    assert client.get(f"/agent/v1/runs/{result.run_id}/artifact").json()["result"] == saved
    with closing(sqlite3.connect(runtime.repository.path)) as db:
        raw = json.loads(db.execute("SELECT result FROM runs WHERE id = ?", (result.run_id,)).fetchone()[0])
    assert raw == legacy
