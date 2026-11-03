const {test} = require("node:test");
const assert = require("node:assert/strict");
const charts = require("../chiller_app/web/chart-utils.js");
const units = {elapsed_s:"s",temp:"°C",power:"kW",heat:"kW",flow:"kg/s",cop:"1",missing:"kW"};
const rows = [{elapsed_s:0,temp:0,power:100,heat:400,flow:20,cop:4,missing:null},
  {elapsed_s:60,temp:-3,power:120,heat:480,flow:20,cop:4,missing:NaN}];
const signals = charts.availableSignals(rows, units, {temp:"温度"});

test("only measured numeric signals become choices; zero is valid, null is not", () => {
  assert.deepEqual(signals.map(s=>s.key), ["temp","power","heat","flow","cop"]);
  assert.equal(signals[0].title,"温度");
});
test("multi selection shares units without mixing temperature, power, flow and COP axes", () => {
  const groups=charts.groupSignals(signals,new Set(signals.map(s=>s.key)));
  assert.equal(groups.size,4);
  assert.deepEqual(groups.get("kW").map(s=>s.key),["power","heat"]);
  assert.deepEqual(groups.get("°C").map(s=>s.key),["temp"]);
});
test("switching to single selection replaces the previous choice", () => {
  let selected=new Set(["temp","power"]);
  selected=charts.selectSignals(selected,"flow",true,true);
  assert.deepEqual([...selected],["flow"]);
  selected=charts.selectSignals(selected,"power",true,false);
  assert.deepEqual([...selected],["flow","power"]);
  selected=charts.selectSignals(selected,"flow",false,false);
  assert.deepEqual([...selected],["power"]);
  assert.equal(charts.groupSignals(signals,new Set()).size,0);
});
test("axis ranges preserve negative, zero and constant values and ignore gaps", () => {
  const extent=charts.valueExtent(rows,[signals[0]]);
  assert.ok(extent[0]<-3 && extent[1]>0);
  assert.equal(charts.valueExtent([{temp:null},{temp:Infinity}],[signals[0]]),null);
  const constant=charts.valueExtent(rows,[signals.at(-1)]);
  assert.ok(constant[0]<4 && constant[1]>4);
});
test("all parameters across a maximum-sized upload can be scaled without spread overflow", () => {
  const bulk=Array.from({length:20000},(_,i)=>({temp:i,power:i*100,heat:null}));
  const extent=charts.valueExtent(bulk,signals);
  assert.ok(extent[1]>1999900 && extent[0]<0);
});
