"""Opt-in generic units never silently become ASHRAE assumptions."""
import copy
import pytest
from chiller_app.api.workbench import WorkbenchRequest,run_workbench
from energy_agent.runtime import AgentRuntime

def source(unit='C'):
    row={'TEI':15.,'TEO':10.,'TCI':30.,'TCO':35.,'FWE':72.,'FWC':90.,'power':100.}
    schema={'column_map':{'TEI_K':'TEI','TEO_K':'TEO','TCI_K':'TCI','TCO_K':'TCO','evap_flow_kg_s':'FWE','cond_flow_kg_s':'FWC','P_W':'power'},
        'temperature_unit':unit,'flow_unit':'m3/h','power_unit':'kW','water_specific_heat_J_kgK':4184.,'water_density_kg_m3':995.586}
    return {'asset_id':'explicit-fixture','records':[row],'schema':schema,'source_unit_policy':'explicit'}

@pytest.mark.parametrize('unit',['C','K','F'])
def test_equivalent_temperatures_preserved_through_repository_and_reanalysis(data_dir,unit):
    s=source(unit)
    if unit!='C':
        for name in ('TEI','TEO','TCI','TCO'):
            s['records'][0][name]=s['records'][0][name]+273.15 if unit=='K' else s['records'][0][name]*9/5+32
    rt=AgentRuntime(data_dir);info=rt.register_dataset(s)
    assert info.source_schema.temperature_unit==info.effective_schema.temperature_unit==unit
    assert info.effective_schema.flow_unit=='m3/h' and info.source_unit_policy=='explicit'
    result=rt.analyze({'asset_id':info.asset_id,'dataset_id':info.dataset_id,'task':'physics'})
    assert result.metrics['cooling_capacity_kW'].value==pytest.approx(72/3600*995.586*4184*5/1000)
    assert result.metrics['power_kW'].value==100.
    assert all(w.code!='SOURCE_SCHEMA_INFERRED' for w in result.warnings)
    artifact=rt.repository.get_run(result.run_id)
    assert artifact['model_output']['metadata']['schema']['temperature_unit']==unit
    assert artifact['model_output']['metadata']['input_inference']['declared_units_preserved']

def test_explicit_suffix_conflict_rejected_not_overridden(data_dir):
    s=source('K');row=s['records'][0];row['TEI_C']=row.pop('TEI');s['schema']['column_map']['TEI_K']='TEI_C'
    with pytest.raises(ValueError,match='单位标记 C.*声明单位 K'):AgentRuntime(data_dir).register_dataset(s)

def test_explicit_flow_unit_label_conflict_rejected(data_dir):
    s=source();s['records'][0]['FWE (gpm)']=s['records'][0].pop('FWE');s['schema']['column_map']['evap_flow_kg_s']='FWE (gpm)'
    with pytest.raises(ValueError,match='us_gpm.*m3/h'):AgentRuntime(data_dir).register_dataset(s)

def test_legacy_mode_still_restores_ashrae_headers():
    s=source();s.pop('asset_id');s['source_unit_policy']='legacy_ashrae'
    result=run_workbench(WorkbenchRequest.model_validate(s))
    assert result['metadata']['schema']['temperature_unit']=='F' and result['metadata']['schema']['flow_unit']=='us_gpm'
