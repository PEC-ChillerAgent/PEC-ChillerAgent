"use strict";
// Execute the production chat script against a small DOM/fetch harness to test
// asynchronous session binding, without any provider requests or UI packages.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname,"../chiller_app/web/chat.js"),"utf8");
const settle = async () => {for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
function deferred(){let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};}
class Element {
  constructor(tag="div"){this.tagName=tag.toUpperCase();this.value="";this.checked=false;this.disabled=false;this.hidden=false;this.children=[];this.events={};this.classList={toggle(){}};this.parentElement={textContent:"input"};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  querySelector(){return null;}
  addEventListener(name,callback){this.events[name]=callback;}
  async fire(name){return this.events[name]?.({preventDefault(){}});}
}
function environment(search="",delays=new Map(),{providerConfigured=true,studentConfigured=false,explanationConfigured=true}={}){
  const elements=new Map(),requests=[];
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const context=id=>({session:{context:{asset_id:id,dataset_id:"ds_"+id}},turns:[]});
  const datasets=["a","b"].map(id=>({asset_id:id,dataset_id:"ds_"+id,row_count:1,source:{name:id},effective_schema:{temperature_unit:"C",flow_unit:"kg/s",power_unit:"kW"}}));
  const location={search};
  const fetch=async(url,options={})=>{
    requests.push({url,options});
    let body;
    if(delays.has(url))return delays.get(url).promise;
    if(url==="/agent/v1/datasets?limit=100")body=datasets;
    else if(url==="/agent/v1/models/chiller")body={records:[]};
    else if(url==="/agent/v1/llm/config")body={configured:providerConfigured,base_url:"https://fixture.example/v1",model:"fixture",requires_api_key:true,has_api_key:true,environment_overrides:[],extra_body:{},timeout_s:45,max_tokens:2048};
    else if(url==="/agent/v1/student-analysis/config")body={enabled:studentConfigured,configured:studentConfigured};
    else if(url==="/agent/v1/analysis/config")body={enabled:explanationConfigured,configured:explanationConfigured};
    else if(url==="/agent/v1/student-shadow/config")body={enabled:false};
    else if(url==="/agent/v1/chat/sessions")body=[{session_id:"a",title:"a"},{session_id:"b",title:"b"}];
    else if(url.startsWith("/agent/v1/chat/sessions/"))body=context(url.split("/").pop());
    else if(url==="/agent/v1/chat/external")body={session_id:JSON.parse(options.body).session_id||"new",turn_id:"turn",user_message:"test",answer:"已收到",segments:[],facts:[],status:"completed",notices:[]};
    else if(url==="/agent/v1/student-analysis")body={session_id:JSON.parse(options.body).session_id||"new-student",turn_id:"student-turn",user_message:"test",answer:"学生选择，程序报告",segments:[],facts:[],status:"limited",analysis_backend:"student_physics",student_analysis:{state:"reported",evidence_markdown:"计算事实"},notices:[]};
    else if(url==="/agent/v1/analysis")body={session_id:"explain",turn_id:"explain-turn",model:"chiller-focused1186",user_message:"test",answer:"学生解释",segments:[{text:"学生解释"}],facts:[],status:"limited",analysis_backend:"student_explanation",report_mode:"student_explanation",student_analysis:{state:"reported",model_authored_factual_text:true},notices:[]};
    else throw new Error("Unexpected fixture route: "+url);
    return {ok:true,json:async()=>body};
  };
  const sandbox={document:{getElementById:get,createElement:tag=>new Element(tag),createTextNode:text=>({text}),querySelector:()=>new Element()},
    Option:class extends Element{constructor(text,value){super();this.textContent=text;this.value=value;}},
    URLSearchParams,location,history:{replaceState(_a,_b,url){location.search=new URL(url,"http://fixture").search;}},
    sessionStorage:{getItem(){return null;},removeItem(){}},fetch};
  vm.runInNewContext(source,sandbox,{filename:"chat.js"});
  return {get,requests,delays,context,response:body=>({ok:true,json:async()=>body})};
}
test("initial data loading blocks submission even after provider config arrives",async()=>{
  const wait=deferred();const env=environment("",new Map([["/agent/v1/datasets?limit=100",wait]]));
  await settle();assert.equal(env.get("chat-send").disabled,true);
  env.get("chat-message").value="must wait";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,0);
  wait.resolve(env.response([]));await settle();assert.equal(env.get("chat-send").disabled,false);
});
test("initial history fetch holds the send lock until the session binding is loaded",async()=>{
  const wait=deferred();const env=environment("?session_id=a",new Map([["/agent/v1/chat/sessions/a",wait]]));
  await settle();assert.equal(env.get("chat-send").disabled,true);
  env.get("chat-message").value="must wait";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,0);
  wait.resolve(env.response(env.context("a")));await settle();
  assert.equal(env.get("chat-dataset").value,"ds_a");assert.equal(env.get("chat-send").disabled,false);
});
test("failed history switch restores the old session and prevents sends during the request",async()=>{
  const env=environment("?session_id=a");await settle();
  const wait=deferred();env.delays.set("/agent/v1/chat/sessions/b",wait);
  env.get("chat-history").value="b";const changing=env.get("chat-history").fire("change");
  assert.equal(env.get("chat-send").disabled,true);
  env.get("chat-message").value="must wait";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,0);
  wait.resolve({ok:false,json:async()=>({detail:"fixture failure"})});await changing;await settle();
  assert.equal(env.get("chat-history").value,"a");assert.equal(env.get("chat-dataset").value,"ds_a");
  assert.equal(env.get("chat-send").disabled,false);
  await env.get("chat-form").fire("submit");
  assert.equal(JSON.parse(env.requests.find(r=>r.url==="/agent/v1/chat/external").options.body).session_id,"a");
});
test("successful history switch binds the next message to the newly displayed session",async()=>{
  const env=environment("?session_id=a");await settle();
  const wait=deferred();env.delays.set("/agent/v1/chat/sessions/b",wait);
  env.get("chat-history").value="b";env.get("chat-history").fire("change");
  wait.resolve(env.response(env.context("b")));await settle();
  assert.equal(env.get("chat-dataset").value,"ds_b");
  env.get("chat-message").value="analyze";await env.get("chat-form").fire("submit");
  assert.equal(JSON.parse(env.requests.find(r=>r.url==="/agent/v1/chat/external").options.body).session_id,"b");
});
test("dataset refresh freezes selection and submission until the captured selection is restored",async()=>{
  const env=environment();await settle();env.get("chat-dataset").value="ds_a";
  const wait=deferred();env.delays.set("/agent/v1/datasets?limit=100",wait);
  const refreshing=env.get("refresh-datasets").fire("click");
  assert.equal(env.get("chat-dataset").disabled,true);assert.equal(env.get("chat-send").disabled,true);
  assert.equal(env.get("chat-history").disabled,true);
  env.get("chat-message").value="must wait";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,0);
  wait.resolve(env.response([{asset_id:"a",dataset_id:"ds_a",row_count:1,source:{},effective_schema:{}}]));
  await refreshing;await settle();assert.equal(env.get("chat-dataset").value,"ds_a");
  await env.get("chat-form").fire("submit");
  assert.equal(JSON.parse(env.requests.find(r=>r.url==="/agent/v1/analysis").options.body).context.dataset_id,"ds_a");
});

test("optional shadow configuration cannot block normal submission",async()=>{
  const wait=deferred();const env=environment("",new Map([["/agent/v1/student-shadow/config",wait]]));
  await settle();assert.equal(env.get("chat-send").disabled,false);
  env.get("analysis-backend").value="provider";await env.get("analysis-backend").fire("change");
  env.get("chat-message").value="normal primary question";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,1);
});

test("shadow refresh only exposes the comparison download after recording",async()=>{
  const cfg=deferred();const env=environment("",new Map([["/agent/v1/student-shadow/config",cfg]]));
  cfg.resolve(env.response({enabled:true}));await settle();
  env.get("analysis-backend").value="provider";await env.get("analysis-backend").fire("change");
  env.get("chat-message").value="normal question";await env.get("chat-form").fire("submit");
  const flat=element=>[element,...(element.children||[]).flatMap(flat)];
  const before=flat(env.get("chat-transcript"));const refresh=before.find(e=>e.textContent==="刷新学生状态"),download=before.find(e=>e.textContent==="下载学生对照");
  assert.ok(refresh);assert.equal(download.hidden,true);
  const wait=deferred();env.delays.set("/agent/v1/chat/sessions/new/turns/turn/student-shadow",wait);
  const pending=refresh.fire("click");assert.equal(refresh.disabled,true);
  wait.resolve(env.response({state:"recorded"}));await pending;
  assert.equal(download.hidden,false);assert.equal(download.href,"/agent/v1/chat/sessions/new/turns/turn/student-shadow/report");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,1);
  assert.ok(flat(env.get("chat-transcript")).some(e=>e.text==="已收到"));
});

test("inspection-only shadow skip names the missing current physics run",async()=>{
  const cfg=deferred();const env=environment("",new Map([["/agent/v1/student-shadow/config",cfg]]));
  cfg.resolve(env.response({enabled:true}));await settle();
  env.get("analysis-backend").value="provider";await env.get("analysis-backend").fire("change");
  env.get("chat-message").value="what units?";await env.get("chat-form").fire("submit");
  const flat=e=>[e,...(e.children||[]).flatMap(flat)],nodes=flat(env.get("chat-transcript"));
  const refresh=nodes.find(e=>e.textContent==="刷新学生状态"),download=nodes.find(e=>e.textContent==="下载学生对照");
  const wait=deferred();env.delays.set("/agent/v1/chat/sessions/new/turns/turn/student-shadow",wait);
  const pending=refresh.fire("click");wait.resolve(env.response({state:"skipped",reason_code:"NO_CURRENT_PHYSICS_RUN"}));await pending;
  assert.ok(flat(env.get("chat-transcript")).some(e=>e.textContent==="本轮未执行物理计算，未调用学生"));
  assert.equal(download.hidden,true);assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,1);
});

test("student mode submits with no teacher configuration and never uses chat endpoint",async()=>{
  const env=environment("",new Map(),{providerConfigured:false,studentConfigured:true,explanationConfigured:false});await settle();
  assert.equal(env.get("chat-send").disabled,true);
  env.get("analysis-backend").value="student_physics";await env.get("analysis-backend").fire("change");
  env.get("chat-dataset").value="ds_a";
  assert.equal(env.get("chat-send").disabled,false);assert.equal(env.get("simulation-options").hidden,true);
  env.get("chat-message").value="计算COP";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,0);
  const request=env.requests.find(r=>r.url==="/agent/v1/student-analysis");assert.ok(request);
  assert.equal(JSON.parse(request.options.body).context.dataset_id,"ds_a");
  assert.equal(env.get("analysis-backend").disabled,true);
  const flat=e=>[e,...(e.children||[]).flatMap(flat)];
  assert.ok(flat(env.get("chat-transcript")).some(e=>e.textContent==="受限报告 · 待审核"));
  assert.ok(flat(env.get("chat-transcript")).some(e=>e.textContent==="完整工具事实（程序提供）"));
  assert.ok(!flat(env.get("chat-transcript")).some(e=>e.textContent==="刷新学生状态"));
});

test("student configuration fetch cannot block normal provider mode",async()=>{
  const wait=deferred();const env=environment("",new Map([["/agent/v1/student-analysis/config",wait]]));
  await settle();assert.equal(env.get("chat-send").disabled,false);
  env.get("analysis-backend").value="student_physics";await env.get("analysis-backend").fire("change");
  assert.equal(env.get("chat-send").disabled,true);
  wait.resolve(env.response({enabled:true,configured:true}));await settle();
  assert.equal(env.get("chat-send").disabled,false);
});

test("student session reload preserves backend and refuses mode mixing",async()=>{
  const session=deferred();const env=environment("?session_id=student",new Map([["/agent/v1/chat/sessions/student",session]]),{studentConfigured:true});
  session.resolve(env.response({session:{context:{asset_id:"a",dataset_id:"ds_a"},analysis_backend:"student_physics"},turns:[]}));await settle();
  assert.equal(env.get("analysis-backend").value,"student_physics");
  env.get("analysis-backend").value="provider";await env.get("analysis-backend").fire("change");
  assert.equal(env.get("analysis-backend").value,"student_physics");
  env.get("chat-message").value="重新算当前数据";await env.get("chat-form").fire("submit");
  const sent=env.requests.find(r=>r.url==="/agent/v1/student-analysis");assert.equal(JSON.parse(sent.options.body).session_id,"student");
  await env.get("new-chat").fire("click");env.get("analysis-backend").value="provider";await env.get("analysis-backend").fire("change");
  assert.equal(env.get("analysis-backend").value,"provider");
});

test("failed student POST never sends a teacher retry",async()=>{
  const post=deferred();const env=environment("",new Map([["/agent/v1/student-analysis",post]]),{studentConfigured:true});await settle();
  env.get("analysis-backend").value="student_physics";await env.get("analysis-backend").fire("change");
  env.get("chat-dataset").value="ds_a";env.get("chat-message").value="分析";
  const pending=env.get("chat-form").fire("submit");post.resolve({ok:false,json:async()=>({detail:"学生不可用"})});await pending;
  assert.equal(env.get("chat-error").hidden,false);assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external").length,0);
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/student-analysis").length,1);
});

test("invalid teacher configuration cannot prevent using an enabled student",async()=>{
  const cfg=deferred();const env=environment("",new Map([["/agent/v1/llm/config",cfg]]),{studentConfigured:true});
  cfg.resolve({ok:false,json:async()=>({detail:"原模型配置无效"})});await settle();
  env.get("analysis-backend").value="student_physics";await env.get("analysis-backend").fire("change");
  assert.equal(env.get("chat-send").disabled,false);
});

test("saved student reports display real headings, tables and linked facts",async()=>{
  const facts=Array.from({length:10},(_,i)=>({fact_id:`F${i+1}`,run_id:"synthetic-run",pointer:"/result/metrics/example/value",label:"测试事实",value:i+1,unit:i%2?"条":"kW",origin:i%2?"sample_count":"measured_derived"}));
  const answer="### 性能指标\n\n|指标|本次结果|有效点数|\n|---|---|---|\n"+Array.from({length:5},(_,i)=>`|测试指标|[F${i*2+1}]|[F${i*2+2}]|`).join("\n");
  const records=[{turn:{analysis_backend:"student_physics",report_mode:"student_selection",status:"limited",session_id:"display-test",turn_id:"synthetic-turn",user_message:"查看报告",answer,facts,segments:[],notices:[],tool_run_ids:["synthetic-run"],student_analysis:{state:"reported"}}}];
  const flat=e=>[e,...(e.children||[]).flatMap(flat)],text=e=>(e.textContent||e.text||"")+(e.children||[]).map(text).join("");
  for(const record of records){
    const pending=deferred(),env=environment("?session_id=display-test",new Map([["/agent/v1/chat/sessions/display-test",pending]]),{studentConfigured:true});
    pending.resolve(env.response({session:{analysis_backend:"student_physics",context:{}},turns:[record.turn]}));await settle();
    const nodes=flat(env.get("chat-transcript")),table=nodes.find(e=>e.tagName==="TABLE");assert.ok(table);
    assert.ok(nodes.some(e=>e.tagName==="H3"&&text(e)==="性能指标"));
    assert.deepEqual(flat(table).filter(e=>e.tagName==="TH").map(text),["指标","本次结果","有效点数"]);
    assert.equal(flat(table).filter(e=>e.tagName==="TBODY")[0].children.length,5);
    assert.ok(!text(table).includes("|---"));
    const references=flat(table).filter(e=>e.tagName==="A");assert.ok(references.length>5);
    assert.ok(references.every(e=>e.href.includes(record.turn.tool_run_ids[0])&&e.rel==="noopener"));
    assert.equal(env.requests.filter(r=>r.options.method==="POST").length,0);
  }
});

test("report markup cannot create HTML, script or arbitrary URL links",async()=>{
  const pending=deferred(),env=environment("?session_id=display-test",new Map([["/agent/v1/chat/sessions/display-test",pending]]),{studentConfigured:true});
  const turn={analysis_backend:"student_physics",report_mode:"student_selection",status:"limited",session_id:"display-test",turn_id:"html-test",user_message:"查看报告",notices:[],facts:[],
    answer:'### 标题\n\n|字段|值|\n|---|---|\n|源列|<img src=x onerror=alert(1)>|\n\n- [点此](javascript:alert(1))\n\n<script>alert(1)</script> [F999]',student_analysis:{state:"reported"}};
  pending.resolve(env.response({session:{analysis_backend:"student_physics",context:{}},turns:[turn]}));await settle();
  const flat=e=>[e,...(e.children||[]).flatMap(flat)],nodes=flat(env.get("chat-transcript"));
  assert.ok(!nodes.some(e=>["SCRIPT","IMG","IFRAME"].includes(e.tagName)));
  assert.ok(!nodes.some(e=>e.tagName==="A"&&String(e.href).startsWith("javascript:")));
  assert.ok(nodes.some(e=>e.tagName==="LI"));
  assert.ok(nodes.some(e=>e.text==="<img src=x onerror=alert(1)>"));
});

test("primary student mode stays visible when unconfigured and never falls back to teacher",async()=>{
  const env=environment("",new Map(),{explanationConfigured:false});await settle();
  assert.equal(env.get("student-explanation-option").hidden,false);
  env.get("analysis-backend").value="student_explanation";await env.get("analysis-backend").fire("change");
  assert.equal(env.get("chat-send").disabled,true);
  env.get("chat-message").value="分析";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.options.method==="POST").length,0);
});

test("reviewed language mode uses its own endpoint and model-authorship label",async()=>{
  const env=environment("",new Map(),{providerConfigured:false,explanationConfigured:true});await settle();
  assert.equal(env.get("student-explanation-option").hidden,false);
  env.get("analysis-backend").value="student_explanation";await env.get("analysis-backend").fire("change");
  env.get("chat-dataset").value="ds_a";env.get("chat-message").value="分析";
  await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/analysis").length,1);
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat/external"||r.url==="/agent/v1/student-analysis").length,0);
  const flat=e=>[e,...(e.children||[]).flatMap(flat)];
  assert.ok(flat(env.get("chat-transcript")).some(e=>e.textContent==="学生撰写解释 · Python 提供数值证据"));
  assert.equal(env.get("analysis-backend").disabled,true);
});
