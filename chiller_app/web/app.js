"use strict";
const $ = id => document.getElementById(id);
const signals = [
  ["TEI_K", "冷冻水进水温度", "10", ["tei", "tei_c", "tei_f", "tei_k", "chilled_in", "冷冻水进水温度"]],
  ["TEO_K", "冷冻水出水温度", "5", ["teo", "teo_c", "teo_f", "teo_k", "chilled_out", "冷冻水出水温度"]],
  ["TCI_K", "冷却水进水温度", "30", ["tci", "tci_c", "tci_f", "tci_k", "condenser_in", "冷却水进水温度"]],
  ["TCO_K", "冷却水出水温度", "35", ["tco", "tco_c", "tco_f", "tco_k", "condenser_out", "冷却水出水温度"]],
  ["evap_flow_kg_s", "冷冻水流量", "72", ["evap_flow_m3_h", "chilled_flow", "冷冻水流量", "冷冻水质量流量", "fwe", "fwe_gpm", "fwe_us_gpm"]],
  ["cond_flow_kg_s", "冷却水流量", "90", ["cond_flow_m3_h", "condenser_flow", "冷却水流量", "冷却水质量流量", "fwc", "fwc_gpm", "fwc_us_gpm"]],
  ["P_W", "实测机组功率（仿真可留空）", "100", ["power_kw", "power", "kw", "机组功率", "机组功率_kw"]],
  ["TSet_K", "冷冻水出水设定温度（可用下方固定值）", "8.89", ["tset", "tset_c", "tset_f", "tset_k", "twe_set", "twe_set_c", "twe_set_f", "twe_set_k", "冷冻水出水设定温度"]],
  ["operating_status", "启停状态（0/1，可用下方固定值）", "1", ["on", "enabled", "运行状态"]]
];
const timeSignals = [
  ["timestamp", "时间（序列仿真可选）", "", ["time", "time(minutes)", "time_minutes", "time(s)", "time_seconds", "elapsed_s", "时间", "datetime"]],
  ["run_id", "连续试验编号（可选）", "", ["run", "试验编号", "test_id"]],
  ["sample_id", "样本编号（可选）", "", ["id", "样本编号"]]
];
const labels = {source_row:"输入行号",run_id:"试验编号",sample_id:"样本编号",timestamp:"输入时间",elapsed_s:"时间 (s)",TEI_C:"冷冻进水 (°C)",TEO_C:"实测冷冻出水 (°C)",TCI_C:"冷却进水 (°C)",TCO_C:"实测冷却出水 (°C)",evap_flow_kg_s:"冷冻流量 (kg/s)",cond_flow_kg_s:"冷却流量 (kg/s)",power_kW:"输入功率 (kW)",cooling_capacity_kW:"实测冷量 (kW)",condenser_heat_kW:"实测冷凝热 (kW)",COP:"实测 COP",energy_balance_error_kW:"实测平衡偏差 (kW)",simulated_TEO_C:"仿真冷冻出水 (°C)",simulated_TCO_C:"仿真冷却出水 (°C)",simulated_cooling_capacity_kW:"模型冷量 (kW)",simulated_condenser_heat_kW:"模型冷凝热 (kW)",simulated_evap_water_kW:"仿真冷冻水侧换热 (kW)",simulated_cond_water_kW:"仿真冷却水侧换热 (kW)",evap_storage_kW:"蒸发侧储热速率 (kW)",cond_storage_kW:"冷凝侧储热速率 (kW)"};
const state = {source:"manual", upload:null, result:null, page:0, busy:false, chartSignals:[], chartSelected:new Set()};
const charts = globalThis.ChillerCharts;
Object.assign(labels,{TSet_C:"冷冻出水设定温度 (°C)",operating_status:"启停状态",simulated_power_kW:"模型压缩机功率 (kW)",simulated_COP:"模型 COP",PLR1:"需求负荷率 PLR1",PLR2:"压缩机负荷率 PLR2",CR:"平均循环比 CR",capFunT:"冷量温度修正",EIRFunT:"能耗温度修正",EIRFunPLR:"能耗负荷修正",curve_out_of_range:"曲线范围外 (0/1)"});
const operation = () => document.querySelector('input[name="operation"]:checked').value;
const unitText = () => ({temp:{C:"°C",K:"K",F:"°F"}[$("temp-unit").value],flow:{"m3/h":"m³/h","kg/s":"kg/s","m3/s":"m³/s",us_gpm:"US gpm"}[$("flow-unit").value],power:$("power-unit").value});

function element(tag, text, className) {const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function clearResult() {state.result=null;$("results").hidden=true;$("empty").hidden=false;$("error").hidden=true;}
function errorMessage(error) {$("error").textContent=error.message || String(error);$("error").hidden=false;}
function updateUI() {
  const sim=operation()==="simulate", file=state.source==="file", series=file && $("sim-kind").value==="series";
  $("manual-input").hidden=file;$("file-input").hidden=!file;$("source-badge").textContent=file?"文件导入":"手动输入";
  $("manual-fields").querySelectorAll("input").forEach(input=>input.disabled=file);
  $("file").disabled=!file;
  document.querySelectorAll("[data-source]").forEach(button=>{const selected=button.dataset.source===state.source;button.classList.toggle("selected",selected);button.setAttribute("aria-pressed",selected);});
  $("simulation-settings").hidden=!sim;$("series-kind-wrap").hidden=!file;$("constant-settings").hidden=series;$("time-mode-wrap").hidden=!series;
  $("sim-input-help").textContent="ElectricEIR 必需：两侧进水温度、两侧正流量、出水设定温度。实测功率与出水温度可留空；启停状态只能是 0/1。";
  $("initial-help").textContent="每组固定初态，留空使用冷冻出水 5°C、冷却出水 25°C；不读取实测出水作为初态。稳态模式忽略初态。";
  $("run").replaceChildren(document.createTextNode(state.busy?"正在处理…":sim?"开始仿真":"开始计算"),element("span",state.busy?"…":"→"));
  $("run-hint").textContent=sim?"ElectricEIR · 性能曲线计算功率 · 机组参数可调整":"无需训练模型，即可计算。";
  $("interval-label").firstChild.textContent=series?"固定采样间隔（秒）":"输出间隔（秒）";
  $("interval").disabled=sim && series && $("time-mode").value!=="interval";
  // Hidden required fields should never prevent a physical calculation.
  $("simulation-settings").querySelectorAll("input,select,textarea").forEach(input=>{if(input.id!=="interval")input.disabled=!sim || !!input.closest("[hidden]");});
  if(sim){
    const steady=$("eir-mode").value==="steady";
    ["tau-e","tau-c","initial-teo","initial-tco"].forEach(id=>$(id).disabled=steady);
  }
  const units=unitText();
  signals.forEach(([key])=>{$("unit-"+key).textContent=key.endsWith("_K")?units.temp:key==="P_W"?units.power:key==="operating_status"?"0/1":units.flow;});
  document.querySelectorAll(".temp-symbol").forEach(span=>span.textContent=units.temp);
}

signals.forEach(([key,title,placeholder])=>{
  const label=element("label",title+" ");const unit=element("span","","field-unit");unit.id="unit-"+key;label.append(unit);
  const input=element("input");input.id="input-"+key;input.type="number";input.step="any";input.placeholder="例如 "+placeholder;if(!key.endsWith("_K"))input.min="0";
  label.append(input);$("manual-fields").append(label);
});
document.querySelectorAll("[data-source]").forEach(button=>button.addEventListener("click",()=>{state.source=button.dataset.source;clearResult();updateUI();}));
$("workbench-form").addEventListener("input",()=>{clearResult();updateUI();});
$("workbench-form").addEventListener("change",()=>{clearResult();updateUI();});
function loadExample() {
  state.source="manual";signals.forEach(([key,,value])=>$("input-"+key).value=value);
  $("temp-unit").value="C";$("flow-unit").value="m3/h";$("power-unit").value="kW";
  if(operation()==="simulate"&&state.catalogue){
    const record=state.catalogue.records.find(r=>r.id===$("eir-record").value),p=record.parameters;
    $("input-TEI_K").value=(p.TEvaLvg_nominal-273.15+5).toFixed(3);
    $("input-TCI_K").value=(p.TConEnt_nominal-273.15).toFixed(3);
    $("input-evap_flow_kg_s").value=(p.mEva_flow_nominal*3600/numeric("density")).toFixed(6);
    $("input-cond_flow_kg_s").value=(p.mCon_flow_nominal*3600/numeric("density")).toFixed(6);
    ["TEO_K","TCO_K","P_W","TSet_K"].forEach(k=>$("input-"+k).value="");
    $("eir-setpoint").value=(p.TEvaLvg_nominal-273.15).toFixed(3);
  }
  clearResult();updateUI();
}
$("example").addEventListener("click",loadExample);$("empty-example").addEventListener("click",loadExample);

async function fetchJSON(url, options) {
  const response=await fetch(url,options);let payload;
  try {payload=await response.json();} catch {throw new Error("服务未返回有效结果，请检查终端中的运行状态。");}
  if(!response.ok){const detail=payload.detail;throw new Error(typeof detail==="string"?detail:Array.isArray(detail)?detail.map(d=>`${d.loc.slice(1).join(".")}: ${d.msg}`).join("；"):"请求失败，请检查输入。");}
  return payload;
}
function renderTable(container, records, keys, titleMap=labels) {
  container.replaceChildren();const table=element("table"), head=element("thead"), tr=element("tr");
  keys.forEach(key=>tr.append(element("th",titleMap[key]||key)));head.append(tr);table.append(head);const body=element("tbody");
  records.forEach(row=>{const line=element("tr");keys.forEach(key=>line.append(element("td",format(row[key]))));body.append(line);});table.append(body);container.append(table);
}
function buildMapping() {
  // Normalize punctuation and units in source headers so FWE (gpm), FWE_gpm
  // and FWE map to the same RP-1043 signal without losing Chinese headers.
  const columns=state.upload.columns, normalize=value=>value.trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g,"");
  const used=new Set();$("mapping-fields").replaceChildren();
  [...signals,...timeSignals].forEach(([key,title,,aliases])=>{
    const label=element("label",title),select=element("select");select.id="map-"+key;select.append(new Option("不提供此字段",""));
    columns.forEach(column=>select.append(new Option(column,column)));
    let match=columns.find(column=>[key,...aliases].some(alias=>normalize(alias)===normalize(column))&&!used.has(column)
      &&state.upload.records.some(row=>row[column]!==null&&row[column]!==undefined&&String(row[column]).trim()!==""));
    if(key==="operating_status"&&match){const values=state.upload.records.map(row=>row[match]).filter(value=>value!==null&&value!==undefined&&String(value).trim()!=="");if(!values.length||values.some(value=>![0,1].includes(Number(value))))match=null;}
    if(match){select.value=match;used.add(match);}label.append(select);$("mapping-fields").append(label);
  });
  $("mapping-panel").hidden=false;
  $("sheet-control").hidden=!state.upload.sheets?.length;
  if(state.upload.sheets?.length){$("sheet-select").replaceChildren(...state.upload.sheets.map(name=>new Option(name,name)));$("sheet-select").value=state.upload.selected_sheet;}
  renderTable($("source-preview"),state.upload.records.slice(0,10),columns,{});
  const names=new Set(columns.map(normalize));
  const hasEvapGpm=["fwe","fwegpm","fweusgpm"].some(name=>names.has(name));
  const hasCondGpm=["fwc","fwcgpm","fwcusgpm"].some(name=>names.has(name));
  if(["tei","teif","teic","teik"].some(name=>names.has(name))
      &&["tci","tcif","tcic","tcik"].some(name=>names.has(name))&&hasEvapGpm&&hasCondGpm){
    $("temp-unit").value=names.has("teif")||names.has("tei")?"F":names.has("teik")?"K":"C";
    $("flow-unit").value="us_gpm";
  }
  else if(["teic","teif","teik"].some(name=>names.has(name)))$("temp-unit").value=names.has("teif")?"F":names.has("teik")?"K":"C";
  if(names.has("evapflowm3h")||names.has("condflowm3h"))$("flow-unit").value="m3/h";
  else if(names.has("evapflowkgs")||names.has("condflowkgs"))$("flow-unit").value="kg/s";
  else if(names.has("evapflowgpm")||names.has("condflowgpm")||hasEvapGpm||hasCondGpm)$("flow-unit").value="us_gpm";
  if(names.has("kw")||names.has("powerkw"))$("power-unit").value="kW";else if(names.has("pw"))$("power-unit").value="W";
  const timeColumn=columns.find(column=>["time","times","timeseconds","timeminutes","elapseds","timestamp","datetime"].includes(normalize(column)));
  if(timeColumn&&state.upload.records.length&&state.upload.records.every(row=>numericValue(row[timeColumn])!==null))$("time-mode").value=/minute/i.test(timeColumn)?"minutes":"seconds";
  refreshUploadReview();
}
async function loadWorkbookSheet(file,sheetName){
  setBusy(true);$("upload-status").textContent=`正在读取工作表“${sheetName}”…`;
  try{const form=new FormData();form.append("file",file);const query=sheetName?`?sheet_name=${encodeURIComponent(sheetName)}`:"";state.upload=await fetchJSON(`/workbench/upload${query}`,{method:"POST",body:form});buildMapping();$("upload-status").textContent=`${state.upload.filename}${state.upload.selected_sheet?` · ${state.upload.selected_sheet}`:""} · ${state.upload.row_count.toLocaleString()} 行。`;
  }catch(error){state.upload=null;$("mapping-panel").hidden=true;$("sheet-control").hidden=true;$("upload-status").textContent="读取失败";errorMessage(error);}finally{setBusy(false);}
}
$("file").addEventListener("change",async()=>{
  const file=$("file").files[0];state.upload=null;$("mapping-panel").hidden=true;$("sheet-control").hidden=true;clearResult();if(!file)return;
  if(file.size>10*1024*1024){errorMessage(new Error("文件不能超过 10 MB。"));return;}
  await loadWorkbookSheet(file,null);
});
$("sheet-select").addEventListener("change",()=>{const file=$("file").files[0];if(file)loadWorkbookSheet(file,$("sheet-select").value);});

function selectedColumn(key){return $("map-"+key)?.value||"";}
function numericValue(value){if(value===null||value===undefined||String(value).trim()==="")return null;const number=Number(value);return Number.isFinite(number)?number:null;}
function normalizedValue(key,value){const n=numericValue(value);if(n===null)return null;
  if(key.endsWith("_K")){const unit=$("temp-unit").value;return unit==="C"?n+273.15:unit==="F"?(n-32)*5/9+273.15:n;}
  if(key.endsWith("_kg_s")){const unit=$("flow-unit").value,configured=Number($("density").value),density=Number.isFinite(configured)&&configured>0?configured:995.586;return unit==="kg/s"?n:unit==="m3/s"?n*density:unit==="us_gpm"?n*3.785411784e-3*density/60:n*density/3600;}
  return n;
}
function refreshUploadReview(){
  if(!state.upload||$("mapping-panel").hidden)return;
  const sim=operation()==="simulate";
  const required=sim?["TEI_K","TCI_K","evap_flow_kg_s","cond_flow_kg_s"]:[];
  const rowCount=state.upload.records.length, missingMappings=required.filter(key=>!selectedColumn(key));
  const requiredSet=new Set(required),requiredInvalidRows=new Set(),mappingIssues=[];
  if(sim&&selectedColumn("operating_status"))requiredSet.add("operating_status");
  if(sim&&selectedColumn("TSet_K"))requiredSet.add("TSet_K");
  const mappedKeys=signals.map(item=>item[0]).filter(key=>selectedColumn(key));
  for(const key of mappedKeys){const column=selectedColumn(key);let count=0;state.upload.records.forEach((row,index)=>{const value=normalizedValue(key,row[column]);let invalid=value===null;
      if(key.endsWith("_K")&&value!==null)invalid ||= value<200||value>400;
      if(key.endsWith("_kg_s")&&value!==null)invalid ||= value<=0;
      if(key==="P_W"&&value!==null)invalid ||= value<0;
      if(key==="operating_status"&&value!==null)invalid ||= ![0,1].includes(value);
      if(invalid){count++;if(requiredSet.has(key))requiredInvalidRows.add(index+1);}
    });if(count)mappingIssues.push(`${signals.find(item=>item[0]===key)?.[1]||key} ${count} 行为空或无效`);
  }
  const usable=sim?Math.max(0,rowCount-requiredInvalidRows.size-(missingMappings.length?rowCount:0)):rowCount;
  const report=$("upload-quality");report.replaceChildren();
  const headline=element("p",`${state.upload.selected_sheet?`工作表：${state.upload.selected_sheet} · `:""}${rowCount.toLocaleString()} 行 · ${sim?`按当前仿真输入可用 ${usable.toLocaleString()} 行 / ${rowCount.toLocaleString()} 行`:"已加载，可按当前列映射计算"}`,missingMappings.length||requiredInvalidRows.size||mappingIssues.length?"quality-warning":"quality-ok");report.append(headline);
  if(missingMappings.length)report.append(element("p","缺少必需列映射："+missingMappings.map(key=>signals.find(item=>item[0]===key)?.[1]||key).join("、")+"。请在下方指定数据列。","quality-detail"));
  if(mappingIssues.length)report.append(element("p","已映射字段检查："+mappingIssues.join("；")+`。示例输入行：${[...new Set([...requiredInvalidRows])].slice(0,8).join(", ")||"请查看对应列"}`,"quality-detail"));
  if(sim&&!selectedColumn("TSet_K"))report.append(element("p","出水设定温度未映射时，将使用仿真设置中的固定设定值。","quality-detail"));
  if(!sim){
    const countComplete=keys=>keys.every(key=>selectedColumn(key))?state.upload.records.filter(raw=>keys.every(key=>{const value=normalizedValue(key,raw[selectedColumn(key)]);return value!==null&&(key.endsWith("_K")?value>=200&&value<=400:key.endsWith("_kg_s")?value>0:key==="P_W"?value>=0:true);})).length:0;
    report.append(element("p",`按当前映射可计算：冷量 ${countComplete(["TEI_K","TEO_K","evap_flow_kg_s"])}/${rowCount} 行 · 冷凝热 ${countComplete(["TCI_K","TCO_K","cond_flow_kg_s"])}/${rowCount} 行 · COP ${countComplete(["TEI_K","TEO_K","evap_flow_kg_s","P_W"])}/${rowCount} 行。`,"quality-detail"));
  }
  const previewKeys=[...signals.map(item=>item[0]),...timeSignals.slice(0,1).map(item=>item[0])].filter(key=>selectedColumn(key));
  const previewLabels=Object.fromEntries(signals.map(([key,title])=>[key,title+(key.endsWith("_K")?" (标准化 °C)":key.endsWith("_kg_s")?" (标准化 kg/s)":key==="P_W"?" (标准化 kW)":"")]).concat([["timestamp","时间"]]));
  const preview=state.upload.records.slice(0,10).map((raw,index)=>{const row={"输入行号":index+1};for(const key of previewKeys){const original=raw[selectedColumn(key)];let value=original;if(key.endsWith("_K")){const k=normalizedValue(key,original);value=k===null?null:k-273.15;}else if(key.endsWith("_kg_s")){value=normalizedValue(key,original);}else if(key==="P_W"){const p=numericValue(original);value=p===null?null:($("power-unit").value==="kW"?p:p/1000);}row[previewLabels[key]||key]=value;}return row;});
  renderTable($("normalized-preview"),preview,Object.keys(preview[0]||{}),{});
  if(sim&&eir&&state.upload.selected_sheet?.toLowerCase().includes("steady"))report.append(element("p","当前是稳态汇总工作表；动态仿真需要连续时间序列，请切换到 Complete Data Set 工作表。","quality-detail"));
  const lowFlowRows=new Set();
  if(sim)for(const key of ["evap_flow_kg_s","cond_flow_kg_s"]){const column=selectedColumn(key);if(column)state.upload.records.forEach((raw,index)=>{const value=normalizedValue(key,raw[column]);if(value!==null&&value<0.063)lowFlowRows.add(index+1);});}
  if(lowFlowRows.size)report.append(element("p",`有 ${lowFlowRows.size} 行流量低于约 1 US gpm 等效值（示例行 ${[...lowFlowRows].slice(0,8).join(", ")}）；可能是停机或启停过渡记录，请结合原始数据确认。该提示不自动删除数据。`,"quality-detail"));
  const statusColumn=state.upload.columns.find(column=>["unitstatus","unitstatusraw","sourceunitstatuscode"].includes(column.trim().toLowerCase().replace(/[^a-z0-9]/g,"")));
  if(sim&&eir&&statusColumn&&!selectedColumn("operating_status")){
    const states=[...new Set(state.upload.records.map(row=>String(row[statusColumn]).trim()).filter(value=>value!==""))].slice(0,8);
    report.append(element("p",`检测到“${statusColumn}”状态码（示例取值：${states.join(", ")}），未自动解释为 0/1。当前仿真使用页面的默认启停状态；请核对运行段。`,"quality-detail"));
  }
  const timeKey=selectedColumn("timestamp");
  if(sim&&$("sim-kind").value==="series"&&timeKey&&["seconds","minutes"].includes($("time-mode").value)){
    const values=state.upload.records.map(row=>numericValue(row[timeKey]));
    const missingTime=values.filter(value=>value===null).length;
    const repeated=values.some((value,index)=>index>0&&value===values[index-1]);
    const reversed=values.some((value,index)=>index>0&&value!==null&&values[index-1]!==null&&value<values[index-1]);
    if(missingTime||repeated||reversed)report.append(element("p",`时间列检查：${missingTime?`${missingTime} 行时间为空或非数值。`:""}${repeated?"存在相邻重复时刻。":""}${reversed?"存在时间倒序。":""}动态仿真要求时间完整且严格递增。`,"quality-detail"));
  }
}
$("mapping-fields").addEventListener("change",refreshUploadReview);
$("temp-unit").addEventListener("change",refreshUploadReview);$("flow-unit").addEventListener("change",refreshUploadReview);$("power-unit").addEventListener("change",refreshUploadReview);
$("workbench-form").addEventListener("change",refreshUploadReview);$("workbench-form").addEventListener("input",refreshUploadReview);

function numeric(id, optional=false) {const value=$(id).value.trim();if(value===""&&optional)return null;const number=Number(value);if(value===""||!Number.isFinite(number))throw new Error("请输入有效数值："+$(id).parentElement.textContent.trim());return number;}
function buildRequest() {
  let records, column_map={};
  if(state.source==="manual"){
    const row={};signals.forEach(([key])=>{const value=numeric("input-"+key,true);if(value!==null){row[key]=value;column_map[key]=key;}});records=[row];
  } else {
    if(!state.upload)throw new Error("请先上传数据文件。");records=state.upload.records;
    [...signals,...timeSignals].forEach(([key])=>{if($("map-"+key).value)column_map[key]=$("map-"+key).value;});
  }
  if(!Object.keys(column_map).length)throw new Error("请先输入工况，或映射数据列。");
  if(new Set(Object.values(column_map)).size!==Object.keys(column_map).length)throw new Error("一个来源列只能映射到一个字段，请检查重复选择。");
  const request={operation:operation(),records,schema:{column_map,temperature_unit:$("temp-unit").value,flow_unit:$("flow-unit").value,power_unit:$("power-unit").value,water_specific_heat_J_kgK:numeric("cp"),water_density_kg_m3:numeric("density")}};
  if(request.operation==="simulate"){
    const kind=state.source==="manual"?"constant":$("sim-kind").value;
    request.simulation={engine:"electric_eir",kind,duration_s:kind==="constant"?numeric("duration")*60:3600,interval_s:numeric("interval"),time_mode:$("time-mode").value,initial_teo:numeric("initial-teo",true),initial_tco:numeric("initial-tco",true)};
    const steady=$("eir-mode").value==="steady";
    Object.assign(request.simulation,{record_id:$("eir-record").value,mode:$("eir-mode").value,setpoint:numeric("eir-setpoint",true),enabled:$("eir-enabled").value==="1",tau_evap_s:steady?30:numeric("tau-e"),tau_cond_s:steady?30:numeric("tau-c")});
    if(steady){request.simulation.initial_teo=null;request.simulation.initial_tco=null;}
    if($("eir-custom").checked){try{request.simulation.performance=JSON.parse($("eir-parameters").value);}catch{throw new Error("自定义机组参数不是有效 JSON。");}}
    if(!request.simulation.record_id&&!request.simulation.performance)throw new Error("请等待机组参数加载或填写自定义参数。");

  }
  return request;
}
function setBusy(busy) {
  state.busy=busy;
  // Freeze the submitted input while the server is calculating.
  document.querySelectorAll("form input,form select,form textarea,form button,#example,#empty-example,#send-to-chat").forEach(input=>input.disabled=busy);
  if(!busy)updateUI();else $("run").textContent="正在处理…";
}
$("workbench-form").addEventListener("submit",async event=>{
  event.preventDefault();if(state.busy)return;clearResult();
  try {
    const request=buildRequest();setBusy(true);
    const result=await fetchJSON("/workbench/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(request)});
    result.metadata.source=state.source==="manual"?"手动输入":state.upload.filename;state.result=result;state.page=0;renderResults();
  } catch(error){errorMessage(error);}finally{setBusy(false);}
});
function format(value, digits=3) {if(value===null||value===undefined||value==="")return "—";return typeof value==="number"?value.toLocaleString("zh-CN",{maximumFractionDigits:digits}):String(value);}
function metric(name, value, unit, foot) {const box=element("div",undefined,"metric");box.append(element("div",name,"metric-name"));const number=element("div",format(value,2),"metric-value");number.append(element("small",unit));box.append(number,element("div",foot,"metric-foot"));return box;}
function renderResults() {
  const result=state.result,sim=result.metadata.operation==="simulate",last=result.records.at(-1);
  $("empty").hidden=true;$("results").hidden=false;$("result-title").textContent=sim?(result.metadata.settings.mode==="steady"?"ElectricEIR 稳态结果":"ElectricEIR 动态仿真结果"):"水侧性能计算结果";
  $("result-subtitle").textContent=`${result.metadata.input_rows.toLocaleString()} 条输入 → ${result.records.length.toLocaleString()} 条输出 · ${sim?"下方指标为最后一个序列的末时刻":"下方指标为最后一条记录"}`;
  $("metrics").replaceChildren(...(sim?[
    metric("仿真冷冻水出水温度",last.simulated_TEO_C,"°C","设定值控制与可用冷量共同决定"),
    metric("模型制冷量",last.simulated_cooling_capacity_kW,"kW","ElectricEIR 机组曲线计算"),
    metric("模型压缩机功率",last.simulated_power_kW,"kW","模型输出；不含水泵与风机"),
    metric("模型 COP",last.simulated_COP,"","模型制冷量 / 模型功率")
  ]:[
    metric("实测制冷量",last.cooling_capacity_kW,"kW","由冷冻水温差与流量计算"),
    metric("实测 COP",last.COP,"","实测冷量 / 输入功率"),
    metric("给定机组功率",last.power_kW,"kW","上传或手动输入的测量值"),
    metric("稳态能量平衡偏差",last.energy_balance_error_kW,"kW","冷凝热 − 制冷量 − 输入功率")
  ]));
  $("interpretation").replaceChildren();
  result.warnings.forEach(w=>{
    $("interpretation").append(element("p",`${w.message} 涉及 ${w.count} 个输出点。`,"note warning"));
    if(w.temperature_ranges_C)$("interpretation").append(element("p",`本次仿真冷冻水出水范围 ${format(w.temperature_ranges_C.TEO_min)}～${format(w.temperature_ranges_C.TEO_max)} °C；冷却水出水范围 ${format(w.temperature_ranges_C.TCO_min)}～${format(w.temperature_ranges_C.TCO_max)} °C。可在上方选择对应温度曲线定位。`,"note"));
  });
  if(result.issues.length)$("interpretation").append(element("p",`发现 ${result.issues.length} 个无效输入，已留空。`+result.issues.slice(0,5).map(i=>`第 ${i.row} 行 ${i.field}：${i.message}`).join(" "),"note issue"));
  if(!result.warnings.length&&!result.issues.length)$("interpretation").append(element("p","本次未触发输入异常或基础物理规则提示；这不等同于机组无故障或模型已通过验证。","note"));
  result.notes.forEach(note=>$("interpretation").append(element("p",note,"note")));
  $("metadata").textContent=JSON.stringify(result.metadata,null,2);$("row-count").textContent=result.records.length.toLocaleString()+" 行";
  $("chart-run").replaceChildren();[...new Set(result.records.map(r=>String(r.run_id)))].forEach(run=>$("chart-run").append(new Option(run,run)));
  state.chartSignals=charts.availableSignals(result.records,result.metadata.output_units,labels);
  resetChartSelection();renderChartPicker();renderChart();renderResultTable();
}
function renderResultTable() {
  const rows=state.result.records,start=state.page*50,sim=state.result.metadata.operation==="simulate";
  const preferred=sim?["run_id","elapsed_s","simulated_TEO_C","simulated_TCO_C","simulated_cooling_capacity_kW","simulated_power_kW","simulated_COP","PLR1","CR","power_kW"]:["source_row","cooling_capacity_kW","power_kW","COP","energy_balance_error_kW"];
  const keys=[...preferred,...Object.keys(rows[0]).filter(k=>!preferred.includes(k))];renderTable($("result-table"),rows.slice(start,start+50),keys);
  $("page-info").textContent=`第 ${state.page+1} / ${Math.ceil(rows.length/50)} 页 · 每页 50 行`;$("prev-page").disabled=state.page===0;$("next-page").disabled=start+50>=rows.length;
}
$("prev-page").addEventListener("click",()=>{if(state.page>0){state.page--;renderResultTable();}});$("next-page").addEventListener("click",()=>{if((state.page+1)*50<state.result.records.length){state.page++;renderResultTable();}});
$("chart-run").addEventListener("change",renderChart);

function resetChartSelection() {
  const sim=state.result.metadata.operation==="simulate";
  const defaults=sim?["simulated_TEO_C","simulated_TCO_C"]:["cooling_capacity_kW","power_kW","condenser_heat_kW"];
  const keys=defaults.filter(key=>state.chartSignals.some(signal=>signal.key===key));
  if(!keys.length && state.chartSignals.length)keys.push(state.chartSignals[0].key);
  state.chartSelected=new Set($("chart-selection-mode").value==="single"?keys.slice(0,1):keys);
}
function renderChartPicker() {
  const picker=$("chart-parameters");picker.replaceChildren();
  const groups=charts.groupSignals(state.chartSignals,new Set(state.chartSignals.map(s=>s.key)));
  for(const [unit,signals] of groups){
    const group=element("fieldset",undefined,"curve-group");group.append(element("legend",unit==="1"?"无量纲":unit));
    const choices=element("div",undefined,"curve-options");
    for(const signal of signals){
      const label=element("label",undefined,"curve-option"),input=element("input"),swatch=element("i");
      input.type="checkbox";input.value=signal.key;input.checked=state.chartSelected.has(signal.key);
      swatch.style.borderTopColor=signal.color;if(signal.dashed)swatch.style.borderTopStyle="dashed";
      label.append(input,swatch,element("span",signal.title));choices.append(label);
      input.addEventListener("change",()=>{
        state.chartSelected=charts.selectSignals(state.chartSelected,signal.key,input.checked,$("chart-selection-mode").value==="single");
        renderChartPicker();renderChart();
        // Keep keyboard navigation on the same control after rebuilding.
        $("chart-parameters").querySelector(`input[value="${signal.key}"]`).focus({preventScroll:true});
      });
    }
    group.append(choices);picker.append(group);
  }
  $("chart-selection-count").textContent=`· 已选 ${state.chartSelected.size} 项`;
}
$("chart-selection-mode").addEventListener("change",()=>{
  if(!state.result)return;
  if($("chart-selection-mode").value==="single")state.chartSelected=new Set([...state.chartSelected].slice(0,1));
  renderChartPicker();renderChart();
});
$("chart-default").addEventListener("click",()=>{if(state.result){resetChartSelection();renderChartPicker();renderChart();}});
$("chart-clear").addEventListener("click",()=>{state.chartSelected.clear();renderChartPicker();renderChart();});

function renderChart() {
  if(!state.result)return;
  const sim=state.result.metadata.operation==="simulate";
  const rows=state.result.records.filter(r=>String(r.run_id)===$("chart-run").value);
  $("chart-title").textContent="自选参数曲线";
  $("chart-caption").textContent=(sim?"横轴为本序列的仿真时间。输入、实测计算量与模拟量通过名称区分。":"横轴为当前序列的记录顺序；连线仅用于查看变化。")+" 同一组使用相同纵轴；缺失值处断线，数据点提示可查看数值。";
  const container=$("chart");container.replaceChildren();
  if(!state.chartSelected.size){container.append(element("p","请选择一个或多个参数查看曲线。","help"));return;}
  for(const [unit,definitions] of charts.groupSignals(state.chartSignals,state.chartSelected)){
    const panel=element("section",undefined,"curve-plot");
    panel.append(element("h4",unit==="1"?"无量纲参数":`参数单位：${unit}`));container.append(panel);
    drawChart(panel,rows,definitions,unit,sim);
  }
}
function drawChart(container, rows, definitions, unit, sim) {
  const extent=charts.valueExtent(rows,definitions);
  if(!extent){container.append(element("p","当前序列中这些参数均无有效数值；可切换序列或选择其他参数。","help"));return;}
  const width=700,height=280,left=58,right=20,top=28,bottom=43;
  const [min,max]=extent;
  const maxX=sim?Math.max(1,rows.at(-1).elapsed_s):Math.max(rows.length-1,1);
  const x=(row,index)=>left+(sim?row.elapsed_s:index)/maxX*(width-left-right),y=value=>height-bottom-(value-min)/(max-min)*(height-top-bottom);
  const ns="http://www.w3.org/2000/svg";const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox",`0 0 ${width} ${height}`);svg.setAttribute("role","img");svg.setAttribute("aria-label",definitions.map(s=>s.title).join("、"));
  function node(tag,attrs,text){const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>n.setAttribute(key,value));if(text!==undefined)n.textContent=text;svg.append(n);return n;}
  for(let i=0;i<5;i++){const value=min+(max-min)*i/4,yy=y(value);node("line",{x1:left,x2:width-right,y1:yy,y2:yy,stroke:"#edf1f4","stroke-dasharray":"4 4"});node("text",{x:left-9,y:yy+4,"text-anchor":"end",fill:"#91a3af","font-size":10},format(value,1));}
  node("text",{x:left,y:13,fill:"#91a3af","font-size":10},unit==="1"?"无量纲":unit);
  for(let i=0;i<5;i++){const fraction=i/4;node("text",{x:left+(width-left-right)*fraction,y:height-bottom+22,"text-anchor":"middle",fill:"#91a3af","font-size":10},sim?format(maxX*fraction,0):String(Math.round(maxX*fraction)+1));}
  node("text",{x:width-right,y:height-3,"text-anchor":"end",fill:"#91a3af","font-size":10},sim?"时间 (s)":"当前序列记录顺序");
  const legend=element("div",undefined,"legend");
  definitions.forEach(({key,title,color,dashed})=>{
    let d="",connected=false;
    rows.forEach((row,index)=>{
      if(!charts.finite(row[key])){connected=false;return;}
      const xx=x(row,index),yy=y(row[key]);d+=`${connected?"L":"M"}${xx.toFixed(2)},${yy.toFixed(2)} `;connected=true;
      // Mark isolated points too, so a valid value between gaps stays visible.
      if(rows.length<40 || (!charts.finite(rows[index-1]?.[key])&&!charts.finite(rows[index+1]?.[key]))){const point=node("circle",{cx:xx,cy:yy,r:rows.length===1?5:2.8,fill:color});const tooltip=document.createElementNS(ns,"title");tooltip.textContent=`${title}: ${format(row[key])} ${unit==="1"?"":unit}`;point.append(tooltip);}
    });
    if(d){node("path",{d,fill:"none",stroke:color,"stroke-width":2,"stroke-dasharray":dashed?"7 4":"none","stroke-linejoin":"round"});}
    const item=element("span",title+(d?"":"（本序列无数据）")),swatch=element("i");swatch.style.borderTopColor=color;if(dashed)swatch.style.borderTopStyle="dashed";item.prepend(swatch);legend.append(item);
  });
  const cursor=node("line",{x1:left,x2:left,y1:top,y2:height-bottom,stroke:"#a0b2bc","stroke-dasharray":"3 3",visibility:"hidden"});
  const readout=element("div","将鼠标移到曲线上查看对应记录。","curve-readout");
  function showAt(fraction){
    const target=Math.max(0,Math.min(1,fraction))*maxX;
    let index;
    if(sim){let lo=0,hi=rows.length-1;while(lo<hi){const mid=Math.floor((lo+hi)/2);if(rows[mid].elapsed_s<target)lo=mid+1;else hi=mid;}index=lo;if(index>0 && target-rows[index-1].elapsed_s<rows[index].elapsed_s-target)index--;}
    else index=Math.min(rows.length-1,Math.max(0,Math.round(target)));
    const row=rows[index],xx=x(row,index);cursor.setAttribute("x1",xx);cursor.setAttribute("x2",xx);cursor.setAttribute("visibility","visible");
    readout.textContent=(sim?`时间 ${format(row.elapsed_s)} s`:`第 ${index+1} 条记录`)+" · "+definitions.map(s=>`${s.title}：${format(row[s.key])}`).join("；");
  }
  svg.addEventListener("pointermove",event=>{const rect=svg.getBoundingClientRect();showAt(((event.clientX-rect.left)/rect.width*width-left)/(width-left-right));});
  const slider=element("input");slider.type="range";slider.min="0";slider.max=String(rows.length-1);slider.value="0";slider.step="1";slider.setAttribute("aria-label","选择曲线记录查看参数值");
  slider.addEventListener("input",()=>{const i=Number(slider.value);showAt((sim?rows[i].elapsed_s:i)/maxX);});
  container.append(svg,legend,readout,slider);
}

function download(name,content,type){const url=URL.createObjectURL(new Blob([content],{type})),link=element("a");link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function csvCell(value){if(value===null||value===undefined)return "";let text=String(value);if(typeof value==="string"&&/^[\s]*[=+@-]/.test(value))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';}
$("export-json").addEventListener("click",()=>{if(state.result)download("chiller_results.json",JSON.stringify(state.result,null,2),"application/json;charset=utf-8");});
$("export-csv").addEventListener("click",()=>{if(!state.result)return;const rows=state.result.records,keys=Object.keys(rows[0]);download("chiller_results.csv","\ufeff"+[keys.map(csvCell).join(","),...rows.map(row=>keys.map(key=>csvCell(row[key])).join(","))].join("\r\n"),"text/csv;charset=utf-8");});
$("template").addEventListener("click",()=>download("chiller_upload_template_C_m3h_kW.csv","\ufeffrun_id,sample_id,elapsed_s,TEI_C,TEO_C,TCI_C,TCO_C,evap_flow_m3_h,cond_flow_m3_h,power_kW,TSet_C,operating_status\r\n","text/csv;charset=utf-8"));
function showPerformanceRecord(){
  const record=state.catalogue.records.find(r=>r.id===$("eir-record").value);if(!record)return;
  const p=record.parameters;
  $("eir-record-info").textContent=`额定冷量 ${format(-p.QEva_flow_nominal/1000)} kW · COP ${p.COP_nominal} · 曲线有效温度：冷冻出水 ${format(p.TEvaLvgMin-273.15)}～${format(p.TEvaLvgMax-273.15)} °C；冷却进水 ${format(p.TConEntMin-273.15)}～${format(p.TConEntMax-273.15)} °C。`;
  $("eir-parameters").value=JSON.stringify(p,null,2);
}
$("eir-record").addEventListener("change",showPerformanceRecord);
fetchJSON("/workbench/eir/catalogue").then(data=>{
  state.catalogue=data;$("eir-record").replaceChildren(...data.records.map(r=>new Option(r.description,r.id)));
  $("eir-record").value=data.default_record_id;showPerformanceRecord();
}).catch(error=>{$("eir-record-info").textContent="加载机组参数失败："+error.message;});
updateUI();

$("send-to-chat").addEventListener("click",async()=>{
  if(state.busy)return;
  try{
    const request=buildRequest(),asset_id=$("agent-asset-id").value.trim();
    if(!asset_id)throw new Error("请先填写机组编号。");
    setBusy(true);
    const dataset=await fetchJSON("/agent/v1/datasets",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
      asset_id,records:request.records,schema:request.schema,
      source:{kind:state.source==="manual"?"inline":"upload",name:state.source==="manual"?"工作台手动工况":state.upload.filename,sheet:state.source==="manual"?null:state.upload.selected_sheet||null}
    })});
    const context={asset_id,dataset_id:dataset.dataset_id};
    if(request.operation==="simulate"){
      context.simulation=request.simulation;
      if(context.simulation.performance)context.simulation.record_id="custom";
    }
    sessionStorage.setItem("chiller_chat_context",JSON.stringify(context));
    location.assign("/chat?dataset_id="+encodeURIComponent(dataset.dataset_id));
  }catch(error){errorMessage(error);}finally{setBusy(false);}
});
