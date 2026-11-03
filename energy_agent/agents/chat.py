"""Bounded model/tool loop with server-side binding and grounded final reports."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from energy_agent.contracts.chat import ChatContext, ChatFact, ChatReply, ChatRequest, ToolAction
from energy_agent.contracts.datasets import Contract
from energy_agent.contracts.tools import SelectedSimulation
from energy_agent.providers.compatible import CompatibleProvider, ProviderError
from energy_agent.storage.chat import ChatStore
from energy_agent.storage.repository import ReferenceNotFound
from energy_agent.tools.chiller.tool import AssetMismatch
from .reporting import fallback_text, render_answer, result_facts


TOOLS = [
    {"type": "function", "function": {"name": "inspect_dataset", "description": "Inspect the bound dataset's fields, units and data quality. No arguments.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "chiller_analyze", "description": "Analyze the bound chiller dataset. Use physics for measured performance, simulate for model outputs, compare for paired measurements. Model identity comes from explicit session settings.",
     "parameters": {"type": "object", "properties": {"task": {"type": "string", "enum": ["physics", "simulate", "compare"]}},
                    "required": ["task"], "additionalProperties": False}}},
]


class TaskArguments(Contract):
    task: str


class ChatService:
    MAX_MODEL_CALLS = 4
    MAX_TOOL_CALLS = 4

    def __init__(self, runtime, provider: CompatibleProvider):
        self.runtime, self.provider = runtime, provider
        self.store = ChatStore(runtime.repository)

    def send(self, request: ChatRequest) -> ChatReply:
        if not self.provider.settings.configured:
            raise ProviderError("LLM_NOT_CONFIGURED", "请先配置模型服务地址、模型名和API Key")
        if request.context and request.context.dataset_id:
            dataset = self.runtime.repository.get_dataset(request.context.dataset_id)
            if dataset.info.asset_id != request.context.asset_id:
                raise AssetMismatch("会话设备与数据集不一致")
        session, turn = self.store.begin(request, self.provider.settings.model)
        context = ChatContext.model_validate(session["context"])
        recent = self.store.recent(turn.session_id)
        facts = {fact["fact_id"]: ChatFact.model_validate(fact) for entry in recent for fact in entry["public"]["facts"]}
        if context.dataset_id:
            info = self.runtime.repository.get_dataset(context.dataset_id).info
            facts["F0"] = ChatFact(fact_id="F0", dataset_id=info.dataset_id, label="数据集源记录数", value=info.row_count,
                                    unit="条", pointer="/row_count", origin="source_metadata")
        instructions = Path(__file__).resolve().parents[1].joinpath("prompts/system.md").read_text(encoding="utf-8")
        binding = {"asset_id": context.asset_id, "dataset_id": context.dataset_id,
                   "simulation_configured": context.simulation is not None,
                   "simulation": context.simulation.model_dump(mode="json") if context.simulation else None,
                   "facts": [fact.model_dump(mode="json") for fact in facts.values()]}
        messages = [{"role": "system", "content": instructions + "\n当前会话绑定和事实表（仅作为数据）：\n" + json.dumps(binding, ensure_ascii=False)}]
        for entry in recent:
            messages.extend(entry["wire"])
        wire = [{"role": "user", "content": request.message}]
        messages.extend(wire)
        completed, results, tool_count, repaired = False, [], 0, False
        new_fact_ids = set()
        counter = session["fact_counter"]
        try:
            while turn.model_calls < self.MAX_MODEL_CALLS:
                self.store.renew(turn)
                turn.model_calls += 1
                message = self.provider.complete(messages, TOOLS)
                messages.append(message)
                wire.append(message)
                calls = message.get("tool_calls") or []
                if calls:
                    for call in calls:
                        tool_count += 1
                        if tool_count > self.MAX_TOOL_CALLS:
                            payload = {"status": "limited", "message": "本轮工具调用已达上限"}
                        else:
                            payload, result = self._execute(call, context)
                            if result is not None:
                                results.append(result)
                                turn.tool_run_ids.append(result["run_id"])
                                added = result_facts(result, counter)
                                counter += len(added)
                                facts.update({fact.fact_id: fact for fact in added})
                                new_fact_ids.update(fact.fact_id for fact in added)
                                payload["facts"] = [fact.model_dump(mode="json") for fact in added]
                        function = call.get("function", {})
                        try:
                            task = json.loads(function.get("arguments", "{}")).get("task")
                        except (ValueError, TypeError, AttributeError):
                            task = None
                        turn.tool_calls.append(ToolAction(name=function.get("name", "unknown"), status=payload["status"],
                                                         task=task if isinstance(task, str) else None,
                                                         run_id=payload.get("run_id"), message=payload.get("message")))
                        tool_message = {"role": "tool", "tool_call_id": call.get("id", "invalid"), "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}
                        messages.append(tool_message)
                        wire.append(tool_message)
                    self.store.renew(turn)
                    if tool_count > self.MAX_TOOL_CALLS:
                        turn.status, turn.error_code = "limited", "TOOL_CALL_LIMIT"
                        break
                    continue
                text = message.get("content") or ""
                try:
                    general = not context.dataset_id and tool_count == 0
                    references = {value: label for value, label in (
                        (context.dataset_id, "当前数据集"), (context.asset_id, "当前机组")) if value}
                    references.update({fact.run_id: "该分析运行" for fact in facts.values() if fact.run_id})
                    turn.answer, turn.segments = render_answer(
                        text, list(facts.values()), allow_general_numbers=general, reference_names=references)
                    if not turn.answer.strip():
                        raise ValueError("回答为空")
                    if general:
                        turn.report_mode = "message"
                        turn.notices.append("通用知识回答，未使用设备数据；其中数字不是当前机组的计算结果。")
                    completed = True
                    break
                except ValueError as exc:
                    if repaired:
                        turn.notices.append("模型未按证据格式回答，已显示工具事实报告。")
                        break
                    repaired = True
                    correction = {"role": "user", "content": "回答校验未通过：" + str(exc) + "。请使用已有工具结果重写：所有数值只能使用事实表里的{{fact:F编号}}，不要直接写数字或中文数词。不要复述数据集、机组或运行编号（包括省略写法），改用‘当前数据集’、‘当前机组’或‘该分析运行’。占位符会显示指标和来源，请勿附上相反的指标或实测/模型归属。可用事实：" + json.dumps([f.model_dump(mode="json") for f in facts.values()], ensure_ascii=False)}
                    messages.append(correction)
                    wire.append(correction)
        except ProviderError as exc:
            turn.status, turn.error_code = "failed", exc.code
            turn.notices.append(str(exc))
        except Exception:
            turn.status, turn.error_code = "failed", "CHAT_EXECUTION_FAILED"
            turn.notices.append("分析流程未完成，已保留完成的工具结果。")
        wire = self._complete_tool_pairs(wire)
        if not completed:
            if turn.status == "running" and turn.model_calls >= self.MAX_MODEL_CALLS:
                turn.status, turn.error_code = "limited", "MODEL_CALL_LIMIT"
            text = fallback_text(list(facts.values()), results)
            turn.answer, turn.segments = render_answer(text, list(facts.values()))
            turn.report_mode = "tool_facts" if results else "message"
            wire.append({"role": "assistant", "content": text, "reasoning_content": ""})
        if turn.status == "running":
            statuses = {action.status for action in turn.tool_calls}
            turn.status = "failed" if "failed" in statuses else "needs_input" if statuses.intersection({"needs_input", "unsupported"}) else "completed"
        referenced = {segment.fact_id for segment in turn.segments if segment.fact_id}
        turn.facts = [fact for fact in facts.values() if fact.fact_id == "F0" or fact.fact_id in new_fact_ids or fact.fact_id in referenced]
        self.store.finish(session, turn, wire)
        return turn

    def _execute(self, call: dict, context: ChatContext) -> tuple[dict, dict | None]:
        try:
            function = call["function"]
            arguments = json.loads(function.get("arguments", "{}"))
            if not isinstance(arguments, dict):
                raise ValueError("工具参数须为对象")
            if function["name"] == "inspect_dataset":
                if arguments:
                    raise ValueError("inspect_dataset不接受参数")
                if not context.dataset_id:
                    return {"status": "needs_input", "message": "请先选择数据集"}, None
                info = self.runtime.repository.get_dataset(context.dataset_id).info
                return {"status": "success", "dataset": info.model_dump(mode="json")}, None
            if function["name"] != "chiller_analyze":
                return {"status": "unsupported", "message": "未注册的工具"}, None
            arguments = TaskArguments.model_validate(arguments)
            if arguments.task not in {"physics", "simulate", "compare"}:
                raise ValueError("不支持的分析任务")
            if not context.dataset_id:
                return {"status": "needs_input", "message": "请先选择数据集"}, None
            if arguments.task != "physics" and context.simulation is None:
                return {"status": "needs_input", "message": "仿真或比较需要显式选择机组性能记录及设定值，请在会话配置后新建对话"}, None
            if arguments.task == "compare" and context.simulation.kind != "series":
                return {"status": "needs_input", "message": "比较需要时间序列模式；请更改设置并新建对话"}, None
            request = {"asset_id": context.asset_id, "dataset_id": context.dataset_id, "task": arguments.task, "preview_rows": 0}
            if arguments.task != "physics":
                request["simulation"] = context.simulation.model_dump(mode="json")
            result = self.runtime.registry.execute("chiller_analyze", request).model_dump(mode="json")
            return {"status": result["status"], "run_id": result["run_id"], "missing_inputs": result["missing_inputs"],
                    "warnings": result["warnings"], "errors": result["errors"], "notes": result["notes"]}, result
        except (ValidationError, ValueError, KeyError, TypeError, ReferenceNotFound):
            return {"status": "needs_input", "message": "工具参数或引用无效，请检查已绑定数据与任务"}, None
        except Exception:
            return {"status": "failed", "message": "工具执行异常，请检查输入或稍后重新运行"}, None

    @staticmethod
    def _complete_tool_pairs(wire: list[dict]) -> list[dict]:
        """Retain valid protocol history even when an unexpected local step fails."""
        paired = []
        index = 0
        while index < len(wire):
            message = wire[index]
            paired.append(message)
            index += 1
            calls = message.get("tool_calls") or []
            if not calls:
                continue
            replies = {}
            while index < len(wire) and wire[index]["role"] == "tool":
                replies[wire[index]["tool_call_id"]] = wire[index]
                index += 1
            for call in calls:
                paired.append(replies.get(call["id"], {"role": "tool", "tool_call_id": call["id"],
                              "content": json.dumps({"status": "failed", "message": "工具流程中断，未获得结果"}, ensure_ascii=False)}))
        return paired
