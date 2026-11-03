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
  constructor(){this.value="";this.checked=false;this.disabled=false;this.hidden=false;this.children=[];this.events={};this.classList={toggle(){}};this.parentElement={textContent:"input"};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  querySelector(){return null;}
  addEventListener(name,callback){this.events[name]=callback;}
  async fire(name){return this.events[name]?.({preventDefault(){}});}
}
function environment(search="",delays=new Map()){
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
    else if(url==="/agent/v1/llm/config")body={configured:true,base_url:"https://fixture.example/v1",model:"fixture",requires_api_key:true,has_api_key:true,environment_overrides:[],extra_body:{},timeout_s:45,max_tokens:2048};
    else if(url==="/agent/v1/chat/sessions")body=[{session_id:"a",title:"a"},{session_id:"b",title:"b"}];
    else if(url.startsWith("/agent/v1/chat/sessions/"))body=context(url.split("/").pop());
    else if(url==="/agent/v1/chat")body={session_id:JSON.parse(options.body).session_id||"new",turn_id:"turn",user_message:"test",answer:"已收到",segments:[],facts:[],status:"completed",notices:[]};
    else throw new Error("Unexpected fixture route: "+url);
    return {ok:true,json:async()=>body};
  };
  const sandbox={document:{getElementById:get,createElement:()=>new Element(),createTextNode:text=>({text}),querySelector:()=>new Element()},
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
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat").length,0);
  wait.resolve(env.response([]));await settle();assert.equal(env.get("chat-send").disabled,false);
});
test("initial history fetch holds the send lock until the session binding is loaded",async()=>{
  const wait=deferred();const env=environment("?session_id=a",new Map([["/agent/v1/chat/sessions/a",wait]]));
  await settle();assert.equal(env.get("chat-send").disabled,true);
  env.get("chat-message").value="must wait";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat").length,0);
  wait.resolve(env.response(env.context("a")));await settle();
  assert.equal(env.get("chat-dataset").value,"ds_a");assert.equal(env.get("chat-send").disabled,false);
});
test("failed history switch restores the old session and prevents sends during the request",async()=>{
  const env=environment("?session_id=a");await settle();
  const wait=deferred();env.delays.set("/agent/v1/chat/sessions/b",wait);
  env.get("chat-history").value="b";const changing=env.get("chat-history").fire("change");
  assert.equal(env.get("chat-send").disabled,true);
  env.get("chat-message").value="must wait";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat").length,0);
  wait.resolve({ok:false,json:async()=>({detail:"fixture failure"})});await changing;await settle();
  assert.equal(env.get("chat-history").value,"a");assert.equal(env.get("chat-dataset").value,"ds_a");
  assert.equal(env.get("chat-send").disabled,false);
  await env.get("chat-form").fire("submit");
  assert.equal(JSON.parse(env.requests.find(r=>r.url==="/agent/v1/chat").options.body).session_id,"a");
});
test("successful history switch binds the next message to the newly displayed session",async()=>{
  const env=environment("?session_id=a");await settle();
  const wait=deferred();env.delays.set("/agent/v1/chat/sessions/b",wait);
  env.get("chat-history").value="b";env.get("chat-history").fire("change");
  wait.resolve(env.response(env.context("b")));await settle();
  assert.equal(env.get("chat-dataset").value,"ds_b");
  env.get("chat-message").value="analyze";await env.get("chat-form").fire("submit");
  assert.equal(JSON.parse(env.requests.find(r=>r.url==="/agent/v1/chat").options.body).session_id,"b");
});
test("dataset refresh freezes selection and submission until the captured selection is restored",async()=>{
  const env=environment();await settle();env.get("chat-dataset").value="ds_a";
  const wait=deferred();env.delays.set("/agent/v1/datasets?limit=100",wait);
  const refreshing=env.get("refresh-datasets").fire("click");
  assert.equal(env.get("chat-dataset").disabled,true);assert.equal(env.get("chat-send").disabled,true);
  assert.equal(env.get("chat-history").disabled,true);
  env.get("chat-message").value="must wait";await env.get("chat-form").fire("submit");
  assert.equal(env.requests.filter(r=>r.url==="/agent/v1/chat").length,0);
  wait.resolve(env.response([{asset_id:"a",dataset_id:"ds_a",row_count:1,source:{},effective_schema:{}}]));
  await refreshing;await settle();assert.equal(env.get("chat-dataset").value,"ds_a");
  await env.get("chat-form").fire("submit");
  assert.equal(JSON.parse(env.requests.find(r=>r.url==="/agent/v1/chat").options.body).context.dataset_id,"ds_a");
});
