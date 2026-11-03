"""Real OpenAI-compatible Chat Completions transport."""

from __future__ import annotations

import httpx

from energy_agent.contracts.chat import LLMSettings


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CompatibleProvider:
    def __init__(self, settings: LLMSettings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        settings = self.settings
        if not settings.configured:
            raise ProviderError("LLM_NOT_CONFIGURED", "请先配置模型服务地址、模型名和API Key")
        headers = {"Content-Type": "application/json"}
        if settings.api_key and settings.api_key.get_secret_value():
            headers["Authorization"] = "Bearer " + settings.api_key.get_secret_value()
        body = {"model": settings.model, "messages": messages, "stream": False,
                "max_tokens": settings.max_tokens, **settings.extra_body}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        try:
            with httpx.Client(timeout=settings.timeout_s, transport=self.transport, follow_redirects=False) as client:
                response = client.post(settings.base_url + "/chat/completions", headers=headers, json=body)
            if response.status_code in {401, 403}:
                raise ProviderError("LLM_AUTH_FAILED", "模型服务鉴权失败，请检查密钥与模型访问权限")
            if response.status_code == 429:
                raise ProviderError("LLM_RATE_LIMITED", "模型服务限流或额度不足，请稍后重试或检查账户")
            if response.status_code >= 400 or response.is_redirect:
                raise ProviderError("LLM_HTTP_ERROR", f"模型服务返回HTTP {response.status_code}，请检查地址、模型及兼容参数")
            payload = response.json()
            message = payload["choices"][0]["message"]
            if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
                raise ValueError("Unexpected message shape")
            content, calls = message.get("content"), message.get("tool_calls")
            if content is not None and not isinstance(content, str):
                raise ValueError("Text responses are required")
            if calls is not None and not isinstance(calls, list):
                raise ValueError("Invalid tool calls")
            call_ids = set()
            for call in calls or []:
                if not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]:
                    raise ValueError("Invalid tool call identity")
                if call["id"] in call_ids:
                    raise ValueError("Duplicate tool call identity")
                call_ids.add(call["id"])
                function = call.get("function")
                if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not isinstance(function.get("arguments"), str):
                    raise ValueError("Invalid function call")
            if not content and not calls:
                raise ValueError("No visible answer or tool calls")
            # Preserve reasoning_content for providers that require it on every
            # subsequent request carrying tools. It is never exposed in public chat.
            return {"role": "assistant", "content": content,
                    **({"tool_calls": calls} if calls else {}),
                    **({"reasoning_content": message["reasoning_content"]} if "reasoning_content" in message else {})}
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError("LLM_TIMEOUT", "模型服务请求超时；未自动重试") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise ProviderError("LLM_CONNECTION_FAILED", "无法连接模型服务，请检查地址和网络") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("LLM_INVALID_RESPONSE", "模型服务返回格式不符合兼容聊天协议") from None
