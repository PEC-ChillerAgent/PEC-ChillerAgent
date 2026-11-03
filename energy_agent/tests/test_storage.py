import math

import pytest
from pydantic import ValidationError

from energy_agent.contracts.datasets import DatasetCreate
from energy_agent.storage.repository import ReferenceNotFound, Repository


def test_dataset_snapshot_survives_restart_and_caller_mutation(data_dir, physics_source):
    repo = Repository(data_dir)
    request = DatasetCreate.model_validate(physics_source)
    info = repo.create_dataset(request)
    request.records[0]["tei"] = 999
    restored = Repository(data_dir).get_dataset(info.dataset_id)
    assert restored.records[0]["tei"] == 10
    assert restored.info.asset_id == "chiller_01"
    assert restored.info.source_schema.water_specific_heat_J_kgK == 4180
    assert restored.info.version == 1
    restored.records[0]["tei"] = -999
    assert repo.get_dataset(info.dataset_id).records[0]["tei"] == 10
    assert repo.create_dataset(DatasetCreate.model_validate(physics_source)).dataset_id != info.dataset_id
    assert len(repo.list_datasets()) == 2


def test_missing_mapping_is_rejected_without_saving(data_dir, physics_source):
    repo = Repository(data_dir)
    physics_source["schema"]["column_map"]["P_W"] = "absent"
    with pytest.raises(ValueError, match="Mapped source columns"):
        repo.create_dataset(DatasetCreate.model_validate(physics_source))
    assert repo.list_datasets() == []


@pytest.mark.parametrize("unit", ["temperature_unit", "flow_unit", "power_unit"])
def test_source_units_are_required(physics_source, unit):
    del physics_source["schema"][unit]
    with pytest.raises(ValidationError):
        DatasetCreate.model_validate(physics_source)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, {"nested": 1}, [1, 2]])
def test_nonfinite_and_nested_measurements_are_rejected(physics_source, value):
    physics_source["records"][0]["tei"] = value
    with pytest.raises(ValidationError):
        DatasetCreate.model_validate(physics_source)


def test_unknown_reference_and_parameterized_lookup(data_dir):
    repo = Repository(data_dir)
    for value in ("unknown", "' OR 1=1 --"):
        with pytest.raises(ReferenceNotFound):
            repo.get_dataset(value)
    with pytest.raises(ReferenceNotFound):
        repo.get_run("unknown")
