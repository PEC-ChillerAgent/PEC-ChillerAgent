"""Single numerical boundary shared with the existing workbench."""

from chiller_app.api.workbench import WorkbenchRequest, run_workbench


def run_model(request: dict) -> dict:
    return run_workbench(WorkbenchRequest.model_validate(request))
