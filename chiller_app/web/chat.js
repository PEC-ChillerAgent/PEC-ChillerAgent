"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const api = "/agent/v1";
  const state = {session:null, datasets:[], configured:false, busy:false, loading:false, ready:false};
  const contextIds = ["chat-dataset","use-simulation","chat-record","chat-mode","chat-kind","chat-setpoint","chat-time-mode","chat-interval","chat-duration","chat-enabled","chat-tau-e","chat-tau-c","chat-initial-e","chat-initial-c","chat-performance"];
  function node(tag,text,kind){const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(kind)value.className=kind;return value;}
  async function request(path, options){
    const response=await fetch(api+path,options);let body;
    try{body=await response.json();}catch{throw new Error("服务未返回有效JSON，请检查后端状态。");}
    if(!response.ok){const detail=body.detail;throw new Error(typeof detail==="string"?detail:detail?.message||JSON.stringify(detail));}
    return body;
  }
  function post(path,body,method="POST"){return request(path,{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
  function showError(error){$("chat-error").textContent=error.message||String(error);$("chat-error").hidden=false;}
  function clearError(){$("chat-error").hidden=true;}
  function blocked(){return state.busy||state.loading||!state.ready;}
  function lockContext(){const locked=blocked();contextIds.forEach(id=>$(id).disabled=locked||!!state.session);$("context-lock").hidden=!state.session;$("chat-send").disabled=locked||!state.configured;$("chat-message").disabled=locked;["new-chat","chat-history","save-provider","test-provider","refresh-history"].forEach(id=>$(id).disabled=locked);$("refresh-datasets").disabled=locked||!!state.session;}
  function updateSimulation(){document.querySelector(".chat-simulation-fields").hidden=!$("use-simulation").checked;$("custom-performance-wrap").hidden=$("chat-record").value!=="custom";}
  function describeDataset(){const info=state.datasets.find(d=>d.dataset_id===$("chat-dataset").value);$("dataset-description").textContent=info?`设备：${info.asset_id} · ${info.row_count.toLocaleString()} 行 · 温标 ${info.effective_schema.temperature_unit} · 流量 ${info.effective_schema.flow_unit} · 功率 ${info.effective_schema.power_unit}`:"可从计算工作台将当前工况转入智能分析。";}
  async function loadDatasets(){
    const selected=$("chat-dataset").value;state.datasets=await request("/datasets?limit=100");
    const requested=new URLSearchParams(location.search).get("dataset_id");
    if(requested&&!state.datasets.some(d=>d.dataset_id===requested))state.datasets.unshift(await request("/datasets/"+encodeURIComponent(requested)));
    $("chat-dataset").replaceChildren(new Option("仅聊天 · 未绑定数据",""),...state.datasets.map(d=>new Option(`${d.asset_id} · ${d.source.name||"数据集"} · ${d.row_count} 行`,d.dataset_id)));
    $("chat-dataset").value=selected||requested||"";describeDataset();
  }
  async function loadModels(){const data=await request("/models/chiller");$("chat-record").replaceChildren(new Option("请选择匹配的机组参数",""),...data.records.map(r=>new Option(r.description,r.id)),new Option("自定义参数","custom"));}
  function applyContext(context){
    if(!context)return;
    $("chat-dataset").value=context.dataset_id||"";describeDataset();
    const cfg=context.simulation;$("use-simulation").checked=!!cfg;
    if(cfg){
      const fields={"chat-record":"record_id","chat-mode":"mode","chat-kind":"kind","chat-setpoint":"setpoint","chat-time-mode":"time_mode","chat-interval":"interval_s","chat-duration":"duration_s","chat-tau-e":"tau_evap_s","chat-tau-c":"tau_cond_s","chat-initial-e":"initial_teo","chat-initial-c":"initial_tco"};
      Object.entries(fields).forEach(([id,key])=>{if(cfg[key]!==undefined)$(id).value=cfg[key]??"";});
      $("chat-enabled").value=cfg.enabled===false?"0":"1";
      if(cfg.performance)$("chat-performance").value=JSON.stringify(cfg.performance,null,2);
    }
    updateSimulation();
  }
  function number(id,optional=false){const text=$(id).value.trim();if(optional&&!text)return null;const value=Number(text);if(!text||!Number.isFinite(value))throw new Error("请检查仿真参数："+$(id).parentElement.textContent.trim());return value;}
  function currentContext(){
    const dataset=state.datasets.find(d=>d.dataset_id===$("chat-dataset").value);
    const context=dataset?{asset_id:dataset.asset_id,dataset_id:dataset.dataset_id}:{};
    if($("use-simulation").checked){
      if(!dataset)throw new Error("仿真需要先选择数据集。");
      if(!$("chat-record").value)throw new Error("请选择匹配的机组性能记录。");
      context.simulation={record_id:$("chat-record").value,mode:$("chat-mode").value,kind:$("chat-kind").value,
        setpoint:number("chat-setpoint",true),time_mode:$("chat-time-mode").value,interval_s:number("chat-interval"),duration_s:number("chat-duration"),
        enabled:$("chat-enabled").value==="1",tau_evap_s:number("chat-tau-e"),tau_cond_s:number("chat-tau-c"),initial_teo:number("chat-initial-e",true),initial_tco:number("chat-initial-c",true)};
      if(context.simulation.record_id==="custom"){try{context.simulation.performance=JSON.parse($("chat-performance").value);}catch{throw new Error("自定义性能参数须为有效JSON。");}}
    }
    return context;
  }
  async function loadConfig(){
    const config=await request("/llm/config");state.configured=config.configured;
    $("llm-base-url").value=config.base_url;$("llm-model").value=config.model;$("llm-requires-key").checked=config.requires_api_key;
    $("llm-timeout").value=config.timeout_s;$("llm-max-tokens").value=config.max_tokens;$("llm-extra").value=JSON.stringify(config.extra_body||{},null,2);
    $("llm-api-key").value="";$("clear-key").checked=false;
    $("key-state").textContent=(config.has_api_key?"已有密钥，服务端不会回显。":"尚未保存密钥。")+(config.environment_overrides.length?" 部分设置由环境变量覆盖。":"");
    $("provider-status").textContent=config.configured?"配置已填写 · "+config.model:"请先配置模型连接";
    $("provider-status").classList.toggle("chat-no-provider",!config.configured);$("provider-panel").open=!config.configured;lockContext();
  }
  async function refreshHistory(){const entries=await request("/chat/sessions");$("chat-history").replaceChildren(new Option("选择已保存的对话",""),...entries.map(s=>new Option(s.title,s.session_id)));$("chat-history").value=state.session||"";}
  function renderTurn(turn){
    const transcript=$("chat-transcript");transcript.querySelector(".chat-welcome")?.remove();
    const container=node("article",undefined,"chat-turn");container.append(node("div",turn.user_message,"chat-user"));
    const assistant=node("div",undefined,"chat-assistant");assistant.append(node("div","智能分析","chat-role-label"));
    const facts=new Map((turn.facts||[]).map(f=>[f.fact_id,f]));
    for(const segment of turn.segments||[]){
      if(segment.fact_id&&facts.has(segment.fact_id)){
        const fact=facts.get(segment.fact_id),link=node("a",segment.text,"chat-fact-link");
        link.href=fact.run_id?`${api}/runs/${encodeURIComponent(fact.run_id)}/artifact`:`${api}/datasets/${encodeURIComponent(fact.dataset_id)}`;
        link.target="_blank";link.rel="noopener";link.title=fact.label+" · "+fact.pointer;assistant.append(link);
      }else assistant.append(document.createTextNode(segment.text));
    }
    if(!turn.segments?.length)assistant.append(document.createTextNode(turn.answer||"处理中…"));
    container.append(assistant);
    const foot=node("div",undefined,"chat-turn-foot"),labels={running:"处理中",completed:"已完成",needs_input:"需要补充输入",failed:"未完成",limited:"达到调用上限"};
    foot.append(node("span",labels[turn.status]||turn.status,"chat-status"+(turn.status!=="completed"?" warning":"")));
    if(turn.report_mode==="tool_facts")foot.append(node("span","工具事实报告","chat-status"));
    if(turn.status!=="running"){
      const download=node("a","下载分析报告");download.href=`${api}/chat/sessions/${encodeURIComponent(turn.session_id)}/turns/${encodeURIComponent(turn.turn_id)}/report`;foot.append(download);
    }
    container.append(foot);
    for(const notice of turn.notices||[])container.append(node("div",notice,"chat-notice"));
    if(turn.tool_calls?.length){const details=node("details",undefined,"chat-runs");details.append(node("summary","工具调用与计算证据"));
      for(const action of turn.tool_calls){const line=node("p",`${action.name}${action.task?" · "+action.task:""} · ${action.status}${action.message?" · "+action.message:""}`);if(action.run_id){const link=node("a"," 查看完整结果");link.href=`${api}/runs/${encodeURIComponent(action.run_id)}/artifact`;link.target="_blank";link.rel="noopener";line.append(link);}details.append(line);}container.append(details);
    }
    transcript.append(container);transcript.scrollTop=transcript.scrollHeight;
  }
  async function openSession(id){
    if(state.busy||state.loading)return;
    const previous=state.session;state.loading=true;lockContext();
    try{
      const view=await request("/chat/sessions/"+encodeURIComponent(id));
      const dataset=view.session.context.dataset_id;
      if(dataset&&!state.datasets.some(d=>d.dataset_id===dataset)){const info=await request("/datasets/"+encodeURIComponent(dataset));state.datasets.unshift(info);$("chat-dataset").append(new Option(`${info.asset_id} · ${info.row_count} 行`,dataset));}
      applyContext(view.session.context);$("chat-transcript").replaceChildren();view.turns.forEach(renderTurn);state.session=id;
      $("chat-history").value=id;history.replaceState(null,"","/chat?session_id="+encodeURIComponent(id));
    }catch(error){$("chat-history").value=previous||"";throw error;}
    finally{state.loading=false;lockContext();}
  }
  function newConversation(){if(blocked())return;state.session=null;$("chat-transcript").replaceChildren(node("div","新对话已准备好。选择数据集后提出问题。","chat-welcome"));$("chat-history").value="";history.replaceState(null,"","/chat");lockContext();clearError();}
  $("chat-form").addEventListener("submit",async event=>{
    event.preventDefault();if(blocked())return;clearError();const text=$("chat-message").value.trim();if(!text)return;
    try{
      if(!state.configured)throw new Error("请先填写模型连接配置并测试连接。");
      const body=state.session?{session_id:state.session,message:text}:{message:text,context:currentContext()};
      state.busy=true;lockContext();$("chat-progress").hidden=false;
      const reply=await post("/chat",body);state.session=reply.session_id;renderTurn(reply);$("chat-message").value="";
      history.replaceState(null,"","/chat?session_id="+encodeURIComponent(state.session));await refreshHistory();
    }catch(error){showError(error);}finally{state.busy=false;$("chat-progress").hidden=true;lockContext();}
  });
  $("chat-message").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();$("chat-form").requestSubmit();}});
  $("save-provider").addEventListener("click",async()=>{
    if(blocked())return;state.busy=true;lockContext();clearError();try{const extra=JSON.parse($("llm-extra").value||"{}");await post("/llm/config",{base_url:$("llm-base-url").value,model:$("llm-model").value,api_key:$("llm-api-key").value||null,
      requires_api_key:$("llm-requires-key").checked,clear_api_key:$("clear-key").checked,timeout_s:Number($("llm-timeout").value),max_tokens:Number($("llm-max-tokens").value),extra_body:extra},"PUT");
      await loadConfig();state.busy=false;newConversation();$("provider-feedback").textContent="配置已保存。可测试连接后开始聊天。";
    }catch(error){showError(error);}finally{state.busy=false;lockContext();}
  });
  $("test-provider").addEventListener("click",async()=>{if(blocked())return;state.busy=true;lockContext();clearError();$("provider-feedback").textContent="正在测试所配置的模型连接…";try{const response=await post("/llm/test",{});$("provider-feedback").textContent="连接测试成功："+response.message;}catch(error){$("provider-feedback").textContent="连接测试未通过。";showError(error);}finally{state.busy=false;lockContext();}});
  $("new-chat").addEventListener("click",newConversation);
  $("chat-history").addEventListener("change",()=>{if(blocked()){$("chat-history").value=state.session||"";return;}if($("chat-history").value)openSession($("chat-history").value).catch(showError);});
  async function refresh(action){if(blocked())return;state.loading=true;lockContext();try{await action();}catch(error){showError(error);}finally{state.loading=false;lockContext();}}
  $("refresh-history").addEventListener("click",()=>refresh(refreshHistory));
  $("refresh-datasets").addEventListener("click",()=>{if(!state.session)return refresh(loadDatasets);});
  $("chat-dataset").addEventListener("change",describeDataset);$("use-simulation").addEventListener("change",updateSimulation);$("chat-record").addEventListener("change",updateSimulation);
  async function initialize(){
    lockContext();
    try{const loaded=await Promise.allSettled([loadDatasets(),loadModels(),loadConfig(),refreshHistory()]);
      const failure=loaded.find(item=>item.status==="rejected");if(failure)throw failure.reason;
      state.ready=true;
      const selectedSession=new URLSearchParams(location.search).get("session_id");
      if(selectedSession)await openSession(selectedSession);
      else {try{const saved=sessionStorage.getItem("chiller_chat_context");if(saved){const context=JSON.parse(saved);if(!new URLSearchParams(location.search).get("dataset_id")||context.dataset_id===$("chat-dataset").value)applyContext(context);sessionStorage.removeItem("chiller_chat_context");}}catch{}}
      updateSimulation();state.ready=true;lockContext();
    }catch(error){showError(error);}
  }
  initialize();
})();
