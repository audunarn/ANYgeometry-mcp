"""Transport-independent MCP runtime with bounded session receipts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Mapping

from anygeometry import GeometryModel, read_geometry, write_geometry
from anygeometry.automation import (
    AutomationError,
    AutomationResponse,
    CommandBatch,
    EditPlan,
    PROTOCOL_VERSION,
    SelectionSpec,
    apply_plan,
    automation_json_schema,
    describe_capabilities,
    describe_entities,
    describe_model,
    execute_query,
    plan_commands,
    select_entities,
    tool_catalog,
)
MAX_OUTPUT_BYTES = 1_048_576
MAX_RECEIPTS_PER_SESSION = 1_024


def _response(request_id: str, result: object = None, error: AutomationError | None = None) -> dict[str, object]:
    response = AutomationResponse(PROTOCOL_VERSION, request_id, error is None, result, error)
    encoded = response.to_dict()
    import json

    if len(json.dumps(encoded, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
        return AutomationResponse(
            PROTOCOL_VERSION,
            request_id,
            False,
            None,
            AutomationError("OUTPUT_TOO_LARGE", "tool output exceeds 1 MiB; request a smaller page or less detail"),
        ).to_dict()
    return encoded


def _request_id(request: object, fallback: str) -> str:
    return str(request.get("request_id", fallback)) if isinstance(request, Mapping) else fallback


@dataclass(slots=True)
class _Session:
    plans: dict[str, EditPlan] = field(default_factory=dict)
    receipts: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)


class GeometryAutomationRuntime:
    """One explicitly bound geometry document and isolated receipt sessions."""

    def __init__(self, geometry_path: str | Path, *, allow_write_back: bool = False) -> None:
        supplied = Path(geometry_path).expanduser()
        resolved = supplied.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("geometry path must be an existing file")
        self._path = resolved
        self._allow_write_back = bool(allow_write_back)
        self._model = read_geometry(resolved)
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def model(self) -> GeometryModel:
        return self._model

    def _session(self, session_id: str) -> _Session:
        if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
            raise AutomationError("MALFORMED_REQUEST", "session ID must be 1..128 characters")
        return self._sessions.setdefault(session_id, _Session())

    def kernel_capabilities(self, request_id: str = "kernel_capabilities") -> dict[str, object]:
        result = dict(describe_capabilities())
        result["json_schema"] = automation_json_schema()
        result["tools"] = list(tool_catalog())
        return _response(request_id, result)

    def model_summary(self, request: Mapping[str, object]) -> dict[str, object]:
        request_id = _request_id(request, "model_summary")
        try:
            return _response(request_id, describe_model(self._model, request))
        except AutomationError as error:
            return _response(request_id, error=error)

    def select_entities(self, request: Mapping[str, object]) -> dict[str, object]:
        request_id = _request_id(request, "select_entities")
        try:
            return _response(request_id, select_entities(self._model, SelectionSpec.from_dict(request)).to_dict())
        except AutomationError as error:
            return _response(request_id, error=error)

    def describe_entities(self, request: Mapping[str, object]) -> dict[str, object]:
        request_id = _request_id(request, "describe_entities")
        try:
            required = {"protocol_version", "request_id", "model_id", "expected_revision", "handles"}
            optional = {"detail", "page_size", "cursor"}
            if set(request) - required - optional or required - set(request):
                raise AutomationError("MALFORMED_REQUEST", "describe_entities requires a protocol header and handles")
            if request["protocol_version"] != PROTOCOL_VERSION:
                raise AutomationError("UNSUPPORTED_PROTOCOL", f"protocol_version must be {PROTOCOL_VERSION}")
            summaries = describe_entities(
                self._model,
                request["handles"],  # type: ignore[arg-type]
                request_id=request_id,
                model_id=request["model_id"],
                expected_revision=request["expected_revision"],  # type: ignore[arg-type]
                detail=bool(request.get("detail", False)),
                page_size=int(request.get("page_size", 100)),
                cursor=request.get("cursor"),  # type: ignore[arg-type]
            )
            return _response(request_id, summaries.to_dict())
        except AutomationError as error:
            return _response(request_id, error=error)

    def query_geometry(self, request: Mapping[str, object]) -> dict[str, object]:
        request_id = _request_id(request, "query_geometry")
        try:
            return _response(request_id, execute_query(self._model, request))
        except AutomationError as error:
            return _response(request_id, error=error)

    def plan_edit(self, request: Mapping[str, object], *, session_id: str = "stdio") -> dict[str, object]:
        request_id = _request_id(request, "plan_edit")
        try:
            with self._lock:
                session = self._session(session_id)
                plan = plan_commands(self._model, CommandBatch.from_dict(request))
                session.plans[plan.digest] = plan
                return _response(request_id, plan.to_dict())
        except AutomationError as error:
            return _response(request_id, error=error)

    def apply_edit(
        self,
        request: Mapping[str, object],
        *,
        session_id: str = "stdio",
    ) -> dict[str, object]:
        request_id = _request_id(request, "apply_edit")
        try:
            required = {
                "protocol_version",
                "request_id",
                "model_id",
                "expected_revision",
                "plan",
                "approved",
            }
            optional = {"write_back"}
            if set(request) - required - optional or required - set(request):
                raise AutomationError(
                    "MALFORMED_REQUEST",
                    "apply_edit requires a model-bound protocol header, plan, and approved",
                )
            if request["protocol_version"] != PROTOCOL_VERSION:
                raise AutomationError("UNSUPPORTED_PROTOCOL", f"protocol_version must be {PROTOCOL_VERSION}")
            if request["approved"] is not True:
                raise AutomationError("APPROVAL_REQUIRED", "apply_edit requires explicit approved=true")
            write_back = request.get("write_back", False)
            if not isinstance(write_back, bool):
                raise AutomationError("MALFORMED_REQUEST", "write_back must be boolean")
            if write_back and not self._allow_write_back:
                raise AutomationError("WRITE_BACK_DISABLED", "server was not started with --allow-write-back")
            plan_data = request["plan"]
            if not isinstance(plan_data, Mapping):
                raise AutomationError("MALFORMED_PLAN", "plan must be an object")
            plan = EditPlan.from_dict(plan_data)
            key = (request_id, plan.digest)
            with self._lock:
                session = self._session(session_id)
                receipt = session.receipts.get(key)
                if receipt is not None:
                    return receipt
                if str(request["model_id"]) != str(self._model.model_id):
                    raise AutomationError("WRONG_MODEL", "request model UUID does not match the active model")
                if request["expected_revision"] != self._model.revision:
                    raise AutomationError(
                        "STALE_REVISION",
                        f"request expected revision {request['expected_revision']}; active revision is {self._model.revision}",
                    )
                # Plans generated in another session remain cryptographically
                # valid, but a same-session stored plan must be byte-equivalent.
                stored = session.plans.get(plan.digest)
                if stored is not None and stored != plan:
                    raise AutomationError("TAMPERED_PLAN", "stored plan and supplied plan disagree")
                result = apply_plan(self._model, plan)
                if write_back:
                    # The only writable path is the canonical startup path.
                    write_geometry(self._path, self._model)
                response = _response(request_id, result.to_dict())
                if len(session.receipts) >= MAX_RECEIPTS_PER_SESSION:
                    oldest = next(iter(session.receipts))
                    del session.receipts[oldest]
                session.receipts[key] = response
                return response
        except AutomationError as error:
            return _response(request_id, error=error)


__all__ = ["GeometryAutomationRuntime", "MAX_OUTPUT_BYTES", "MAX_RECEIPTS_PER_SESSION"]
