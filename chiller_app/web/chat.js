"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const api = "/agent/v1";
  const state = {session:null, datasets:[], configured:false, busy:false, loading:false, ready:false, shadowEnabled:false,
    backend:"student_explanation", studentConfigured:false, studentConfigLoaded:false, explanationConfigured:false, providerModel:""};
  const contextIds = ["chat-dataset","use-simulation","chat-record","chat-mode","chat-kind","chat-setpoint","chat-time-mode","chat-interval","chat-duration","chat-enabled","chat-tau-e","chat-tau-c","chat-initial-e","chat-initial-c","chat-performance"];
  function node(tag,text,kind){const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(kind)value.className=kind;return value;}
  function appendFactText(parent,text,facts){
    let offset=0;
    for(const match of text.matchAll(/\[(F\d+)\]/g)){
      parent.append(document.createTextNode(text.slice(offset,match.index)));
      const fact=facts.get(match[1]);
      if(fact){const link=node("a",match[0],"chat-fact-link");
        link.href=fact.run_id?`${api}/runs/${encodeURIComponent(fact.run_id)}/artifact`:`${api}/datasets/${encodeURIComponent(fact.dataset_id)}`;
        link.target="_blank";link.rel="noopener";link.title=fact.label+" · "+fact.pointer;parent.append(link);
      }else parent.append(document.createTextNode(match[0]));
      offset=match.index+match[0].length;
    }
    parent.append(document.createTextNode(text.slice(offset)));
  }
  function appendProgramReport(parent,text,facts){
    // Small code-owned Markdown subset. Never interpret HTML, URLs or scripts.
    const lines=text.split(/\r?\n/),cells=line=>line.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(s=>s.trim());
    const separator=line=>line!==undefined&&cells(line).length>1&&cells(line).every(s=>/^:?-{3,}:?$/.test(s));
    const tableAt=i=>lines[i]?.trim().startsWith("|")&&separator(lines[i+1]);
    let i=0;
    while(i<lines.length){
      if(!lines[i].trim()){i++;continue;}
      const heading=lines[i].match(/^\s*(#{1,4})\s+(.+)$/);
      if(heading){const h=node("h"+Math.min(4,heading[1].length));appendFactText(h,heading[2],facts);parent.append(h);i++;continue;}
      if(tableAt(i)){
        const headings=cells(lines[i]),wrap=node("div",undefined,"chat-report-table"),table=node("table"),head=node("thead"),row=node("tr"),body=node("tbody");
        for(const value of headings){const cell=node("th");appendFactText(cell,value,facts);row.append(cell);}head.append(row);table.append(head);i+=2;
        while(i<lines.length&&lines[i].trim().startsWith("|")&&cells(lines[i]).length===headings.length){
          const tr=node("tr");for(const value of cells(lines[i])){const cell=node("td");appendFactText(cell,value,facts);tr.append(cell);}body.append(tr);i++;
        }table.append(body);wrap.append(table);parent.append(wrap);continue;
      }
      const list=lines[i].match(/^\s*(?:([-*])\s+|(\d+)\.\s+)(.+)$/);
      if(list){const ordered=!!list[2],group=node(ordered?"ol":"ul");
        while(i<lines.length){const item=lines[i].match(/^\s*(?:([-*])\s+|(\d+)\.\s+)(.+)$/);if(!item||!!item[2]!==ordered)break;
          const li=node("li");appendFactText(li,item[3],facts);group.append(li);i++;
        }parent.append(group);continue;
      }
      const parts=[lines[i++]];
      while(i<lines.length&&lines[i].trim()&&!/^\s*#{1,4}\s|^\s*(?:[-*]\s|\d+\.\s)/.test(lines[i])&&!tableAt(i))parts.push(lines[i++]);
      const p=node("p");appendFactText(p,parts.join("\n"),facts);parent.append(p);
    }
  }
  async function request(path, options){
    const response=await fetch(api+path,options);let body;
    try{body=await response.json();}catch{throw new Error("服务未返回有效JSON，请检查后端状态。");}
    if(!response.ok){const detail=body.detail;throw new Error(typeof detail==="string"?detail:detail?.message||JSON.stringify(detail));}
    return body;
  }
  function post(path,body,method="POST"){return request(path,{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
  function showError(error){$("chat-error").textContent=error.message||String(error);$("chat-error").hidden=false;}
  function clearError(){$("chat-error").hidden=true;}
  function isStudentBackend(){return state.backend==="student_physics"||state.backend==="student_explanation";}
  function backendConfigured(){return state.backend==="student_explanation"?state.explanationConfigured:state.backend==="student_physics"?state.studentConfigured:state.configured;}
  function blocked(){return state.busy||state.loading||!state.ready;}
  function lockContext(){const locked=blocked();contextIds.forEach(id=>$(id).disabled=locked||!!state.session);$("analysis-backend").disabled=locked||!!state.session;$("context-lock").hidden=!state.session;$("chat-send").disabled=locked||!backendConfigured();$("chat-message").disabled=locked;["new-chat","chat-history","save-provider","test-provider","refresh-history"].forEach(id=>$(id).disabled=locked);$("refresh-datasets").disabled=locked||!!state.session;}
  function describeMode(){
    const student=isStudentBackend();$("analysis-backend").value=state.backend;
    $("simulation-options").hidden=student;$("provider-panel").hidden=student;
    $("analysis-mode-description").textContent=state.backend==="student_explanation"?"先执行 Python 计算，再由 focused1186 根据本次证据回答。支持单条物理工况；服务异常时显示工具事实，不自动调用外部模型。":student
      ?"先执行 Python 计算，再由学生选择解释重点，程序生成报告。不调用 DeepSeek。仅支持单条物理工况；每条问题须写完整，暂不理解跨问题指代。"
      :"使用你明确配置的外部模型，可按问题调用计算、仿真工具。外部调用可能产生费用。";
    $("provider-status").textContent=student?(backendConfigured()?"focused1186 · 连接待实际验证":state.studentConfigLoaded?"请先启动学生服务并配置连接":"正在读取学生配置")
      :(state.configured?"配置已填写 · "+state.providerModel:"请先配置原模型，或选择已启用的学生模式");
    $("provider-status").classList.toggle("chat-no-provider",!backendConfigured());
  }
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
    const config=await request("/llm/config");state.configured=config.configured;state.providerModel=config.model;
    $("llm-base-url").value=config.base_url;$("llm-model").value=config.model;$("llm-requires-key").checked=config.requires_api_key;
    $("llm-timeout").value=config.timeout_s;$("llm-max-tokens").value=config.max_tokens;$("llm-extra").value=JSON.stringify(config.extra_body||{},null,2);
    $("llm-api-key").value="";$("clear-key").checked=false;
    $("key-state").textContent=(config.has_api_key?"已有密钥，服务端不会回显。":"尚未保存密钥。")+(config.environment_overrides.length?" 部分设置由环境变量覆盖。":"");
    $("provider-panel").open=!config.configured;describeMode();lockContext();
  }
  async function refreshHistory(){const entries=await request("/chat/sessions");$("chat-history").replaceChildren(new Option("选择已保存的对话",""),...entries.map(s=>new Option(s.title,s.session_id)));$("chat-history").value=state.session||"";}
  async function loadShadowConfig(){try{state.shadowEnabled=!!(await request("/student-shadow/config")).enabled;}catch{state.shadowEnabled=false;}}
  async function loadStudentConfig(){try{const config=await request("/student-analysis/config");state.studentConfigured=!!config.enabled&&!!config.configured;}catch{state.studentConfigured=false;}finally{state.studentConfigLoaded=true;describeMode();lockContext();}}
  async function loadExplanationConfig(){try{const config=await request("/analysis/config");state.explanationConfigured=!!config.enabled&&!!config.configured;}catch{state.explanationConfigured=false;}finally{$("student-explanation-option").hidden=false;$("student-explanation-option").disabled=false;describeMode();lockContext();}}
  function renderTurn(turn){
    const transcript=$("chat-transcript");transcript.querySelector(".chat-welcome")?.remove();
    const container=node("article",undefined,"chat-turn");container.append(node("div",turn.user_message,"chat-user"));
    const isStudent=turn.analysis_backend==="student_physics"||turn.analysis_backend==="student_explanation";
    const assistant=node("div",undefined,"chat-assistant");assistant.append(node("div",turn.report_mode==="student_explanation"?"学生撰写解释 · Python 提供数值证据":isStudent?"学生物理分析 · 程序提供事实正文":"智能分析","chat-role-label"));
    const facts=new Map((turn.facts||[]).map(f=>[f.fact_id,f]));
    if(isStudent&&turn.report_mode==="student_selection"){
      const report=node("div",undefined,"chat-program-report");appendProgramReport(report,turn.answer||"",facts);assistant.append(report);
    }else for(const segment of turn.segments||[]){
      if(segment.fact_id&&facts.has(segment.fact_id)){
        const fact=facts.get(segment.fact_id),link=node("a",segment.text,"chat-fact-link");
        link.href=fact.run_id?`${api}/runs/${encodeURIComponent(fact.run_id)}/artifact`:`${api}/datasets/${encodeURIComponent(fact.dataset_id)}`;
        link.target="_blank";link.rel="noopener";link.title=fact.label+" · "+fact.pointer;assistant.append(link);
      }else assistant.append(document.createTextNode(segment.text));
    }
    if(!(isStudent&&turn.report_mode==="student_selection")&&!turn.segments?.length)assistant.append(document.createTextNode(turn.answer||"处理中…"));
    container.append(assistant);
    const foot=node("div",undefined,"chat-turn-foot"),labels={running:"处理中",completed:"已完成",needs_input:"需要补充输入",failed:"未完成",limited:"达到调用上限"};
    foot.append(node("span",isStudent&&turn.status==="limited"?(turn.student_analysis?.state==="reported"?"受限报告 · 待审核":"当前范围未覆盖"):labels[turn.status]||turn.status,"chat-status"+(turn.status!=="completed"?" warning":"")));
    if(isStudent)foot.append(node("span","DeepSeek 调用：0","chat-status"));
    if(turn.report_mode==="tool_facts")foot.append(node("span","工具事实报告","chat-status"));
    if(turn.status!=="running"){
      const download=node("a","下载分析报告");download.href=`${api}/chat/sessions/${encodeURIComponent(turn.session_id)}/turns/${encodeURIComponent(turn.turn_id)}/report`;foot.append(download);
    }
    if(state.shadowEnabled&&!isStudent&&turn.status!=="running"){
      const shadowPath=`/chat/sessions/${encodeURIComponent(turn.session_id)}/turns/${encodeURIComponent(turn.turn_id)}/student-shadow`;
      const status=node("span","学生对照待检查","chat-status"),refresh=node("button","刷新学生状态","chat-shadow-refresh"),download=node("a","下载学生对照");
      refresh.type="button";download.href=api+shadowPath+"/report";download.hidden=true;
      refresh.addEventListener("click",async()=>{refresh.disabled=true;try{const result=await request(shadowPath);
        const labels={queued:"学生对照生成中",started:"学生对照生成中",recorded:"学生对照已保存",failed:"学生服务未完成对照",skipped:"当前工况未进入学生试用范围",skipped_busy:"学生服务忙碌，本条未采集",configuration_error:"学生连接配置需检查",not_recorded:"本条尚无学生对照"};
        status.textContent=result.state==="skipped"&&result.reason_code==="NO_CURRENT_PHYSICS_RUN"
          ?"本轮未执行物理计算，未调用学生":labels[result.state]||"学生对照状态待检查";
        download.hidden=result.state!=="recorded";
      }catch{status.textContent="暂时无法读取学生对照";}finally{refresh.disabled=false;}});
      foot.append(status,refresh,download);
    }
    container.append(foot);
    for(const notice of turn.notices||[])container.append(node("div",notice,"chat-notice"));
    if(turn.student_analysis?.evidence_markdown){
      const evidence=node("details",undefined,"chat-runs");evidence.append(node("summary","完整工具事实（程序提供）"));
      const body=node("div",undefined,"chat-program-report");appendProgramReport(body,turn.student_analysis.evidence_markdown,facts);evidence.append(body);container.append(evidence);
    }
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
      state.backend=view.session.analysis_backend||"provider";describeMode();applyContext(view.session.context);$("chat-transcript").replaceChildren();view.turns.forEach(renderTurn);state.session=id;
      $("chat-history").value=id;history.replaceState(null,"","/chat?session_id="+encodeURIComponent(id));
    }catch(error){$("chat-history").value=previous||"";throw error;}
    finally{state.loading=false;lockContext();}
  }
  function newConversation(){if(blocked())return;state.session=null;$("chat-transcript").replaceChildren(node("div","新对话已准备好。选择数据集后提出问题。","chat-welcome"));$("chat-history").value="";history.replaceState(null,"","/chat");lockContext();clearError();}
  $("chat-form").addEventListener("submit",async event=>{
    event.preventDefault();if(blocked())return;clearError();const text=$("chat-message").value.trim();if(!text)return;
    try{
      if(!backendConfigured())throw new Error(isStudentBackend()?"学生分析尚未启用或凭据文件缺失；请按本机启动说明配置。":"请先填写模型连接配置并测试连接。");
      const body=state.session?{session_id:state.session,message:text}:{message:text,context:currentContext()};
      state.busy=true;lockContext();$("chat-progress").hidden=false;
      const reply=await post(state.backend==="student_explanation"?"/analysis":state.backend==="student_physics"?"/student-analysis":"/chat/external",body);state.session=reply.session_id;renderTurn(reply);$("chat-message").value="";
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
  $("analysis-backend").addEventListener("change",()=>{
    if(blocked()||state.session){$("analysis-backend").value=state.backend;return;}
    state.backend=["student_physics","student_explanation"].includes($("analysis-backend").value)?$("analysis-backend").value:"provider";
    if(isStudentBackend())$("use-simulation").checked=false;
    updateSimulation();describeMode();lockContext();clearError();
  });
  $("chat-history").addEventListener("change",()=>{if(blocked()){$("chat-history").value=state.session||"";return;}if($("chat-history").value)openSession($("chat-history").value).catch(showError);});
  async function refresh(action){if(blocked())return;state.loading=true;lockContext();try{await action();}catch(error){showError(error);}finally{state.loading=false;lockContext();}}
  $("refresh-history").addEventListener("click",()=>refresh(refreshHistory));
  $("refresh-datasets").addEventListener("click",()=>{if(!state.session)return refresh(loadDatasets);});
  $("chat-dataset").addEventListener("change",describeDataset);$("use-simulation").addEventListener("change",updateSimulation);$("chat-record").addEventListener("change",updateSimulation);
  async function initialize(){
    void loadShadowConfig();
    void loadStudentConfig();
    void loadExplanationConfig();
    lockContext();
    try{const loaded=await Promise.allSettled([loadDatasets(),loadModels(),loadConfig().catch(error=>{state.configured=false;describeMode();showError(error);}),refreshHistory()]);
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
