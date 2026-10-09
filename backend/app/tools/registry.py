"""Tool framework: typed arguments, role gating, uniform results and execution tracing.

Security properties enforced here (and tested):
* Arguments are validated with `extra="forbid"` models - a model-supplied `tenant_id`,
  `sql`, or any unknown field is rejected, not ignored.
* Tenant and user identity come from `ToolContext` (set by the server from the API key),
  never from model output.
* Only registered tools can run; unknown names are rejected and audited.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from ..auth import Principal
from ..llm.base import ToolSpec
from ..models import AuditLog
from ..retrieval.hybrid import HybridRetriever


class StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(BaseModel):
    id: str
    type: str  # document | product | inventory | order | calculation | action
    title: str
    snippet: str = ""
    meta: dict[str, Any] = {}


class ToolOutput(BaseModel):
    summary: str
    data: dict[str, Any] = {}
    sources: list[Source] = []


@dataclass
class ToolContext:
    db: Session
    principal: Principal
    retriever: HybridRetriever
    conversation_id: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[StrictArgs]
    handler: Callable[[ToolContext, Any], ToolOutput]
    min_role: str = "viewer"
    mutating: bool = False  # True only for tools that create *pending* (unexecuted) actions

    def spec(self) -> ToolSpec:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)


@dataclass
class ToolExecution:
    name: str
    arguments: dict
    ok: bool
    output: ToolOutput | None = None
    error: str | None = None
    duration_ms: float = 0.0
    call_id: str = ""

    def to_llm_content(self, limit: int = 7000) -> str:
        if self.ok and self.output:
            body = {"ok": True, **self.output.model_dump()}
        else:
            body = {"ok": False, "error": self.error}
        text = json.dumps(body, ensure_ascii=False, default=str)
        if len(text) > limit:
            text = text[:limit] + '..."}'
        # Tool results are untrusted *data*; the framing is repeated in the system prompt.
        return f'<tool_result name="{self.name}" trust="data-only">{text}</tool_result>'

    def trace(self) -> dict:
        return {
            "id": self.call_id, "name": self.name, "arguments": self.arguments, "ok": self.ok,
            "summary": self.output.summary if self.output else None, "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
            "result": self.output.data if self.output else None,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def specs_for(self, principal: Principal) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values() if principal.can(t.min_role)]

    def execute(self, ctx: ToolContext, name: str, arguments: dict, call_id: str = "") -> ToolExecution:
        start = time.perf_counter()
        ex = ToolExecution(name=name, arguments=arguments, ok=False, call_id=call_id)
        tool = self._tools.get(name)
        if tool is None:
            self._audit(ctx, "guardrail.unknown_tool", {"tool": name})
            ex.error = f"Unknown tool '{name}'. Available tools: {', '.join(self._tools)}."
        elif not ctx.principal.can(tool.min_role):
            self._audit(ctx, "guardrail.forbidden_tool", {"tool": name, "role": ctx.principal.role})
            ex.error = f"Permission denied: '{name}' requires role '{tool.min_role}'."
        else:
            try:
                args = tool.args_model.model_validate(arguments)
                ex.output = tool.handler(ctx, args)
                ex.ok = True
            except ValidationError as exc:
                self._audit(ctx, "guardrail.invalid_tool_args", {"tool": name, "args": arguments})
                ex.error = "Invalid arguments: " + "; ".join(
                    f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors())
            except ToolError as exc:
                ex.error = str(exc)
        ex.duration_ms = (time.perf_counter() - start) * 1000
        return ex

    @staticmethod
    def _audit(ctx: ToolContext, event: str, detail: dict) -> None:
        ctx.db.add(AuditLog(tenant_id=ctx.principal.tenant_id, user_id=ctx.principal.user_id,
                            event=event, detail=detail))
        ctx.db.commit()


class ToolError(Exception):
    """A user-presentable tool failure (not a bug): bad SKU, not found, permission..."""
