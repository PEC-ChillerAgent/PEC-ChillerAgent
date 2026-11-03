"""Public conversation, provider configuration and grounded report contracts."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, SecretStr, field_validator, model_validator

from .datasets import Contract
from .tools import SelectedSimulation


class LLMSettings(Contract):
    base_url: str = ""
    model: str = ""
    api_key: SecretStr | None = Field(default=None, repr=False)
    requires_api_key: bool = True
    timeout_s: float = Field(default=45, ge=1, le=60)
    max_tokens: int = Field(default=2048, ge=64, le=8192)
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return value
        if value.endswith("/chat/completions"):
            value = value[:-len("/chat/completions")]
        parsed = urlsplit(value)
        try:
            parsed.port
        except ValueError:
            raise ValueError("服务地址端口无效") from None
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("请填写不含凭据或查询参数的服务地址")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("远程服务须使用HTTPS；本地服务可使用HTTP")
        return value

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("extra_body")
    @classmethod
    def reserved_parameters(cls, value: dict) -> dict:
        reserved = {"model", "messages", "tools", "tool_choice", "stream", "max_tokens"}
        if reserved.intersection(value):
            raise ValueError("extra_body不能覆盖模型、消息或工具等核心参数")
        return value

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and (not self.requires_api_key or self.api_key and self.api_key.get_secret_value().strip()))


class LLMConfigUpdate(LLMSettings):
    clear_api_key: bool = False


class ChatContext(Contract):
    asset_id: str | None = None
    dataset_id: str | None = None
    simulation: SelectedSimulation | None = None

    @model_validator(mode="after")
    def paired_binding(self):
        if bool(self.asset_id) != bool(self.dataset_id):
            raise ValueError("asset_id和dataset_id须同时提供")
        if self.simulation and not self.dataset_id:
            raise ValueError("仿真设置须关联数据集")
        return self


class ChatRequest(Contract):
    message: str = Field(min_length=1, max_length=12000)
    session_id: str | None = None
    context: ChatContext | None = None

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空")
        return value.strip()

    @model_validator(mode="after")
    def immutable_context(self):
        if self.session_id and self.context is not None:
            raise ValueError("已有会话的绑定不可变；更换数据集请新建会话")
        return self


class ChatFact(Contract):
    fact_id: str
    run_id: str | None = None
    dataset_id: str | None = None
    label: str
    value: float
    unit: str
    pointer: str
    evidence_id: str | None = None
    origin: str


class AnswerSegment(Contract):
    text: str = ""
    fact_id: str | None = None


class ToolAction(Contract):
    name: str
    status: str
    task: str | None = None
    run_id: str | None = None
    message: str | None = None


class ChatReply(Contract):
    session_id: str
    turn_id: str
    created_at: str
    user_message: str
    answer: str
    segments: list[AnswerSegment] = Field(default_factory=list)
    facts: list[ChatFact] = Field(default_factory=list)
    tool_run_ids: list[str] = Field(default_factory=list)
    tool_calls: list[ToolAction] = Field(default_factory=list)
    status: Literal["running", "completed", "needs_input", "failed", "limited"] = "completed"
    report_mode: Literal["model", "tool_facts", "message"] = "model"
    model: str = ""
    model_calls: int = 0
    error_code: str | None = None
    notices: list[str] = Field(default_factory=list)
