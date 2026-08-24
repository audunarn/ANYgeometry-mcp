from __future__ import annotations

from pathlib import Path

from anygeometry import GeometryModel, read_geometry, write_geometry
from anygeometry_mcp import GeometryAutomationRuntime
from anygeometry_mcp.server import build_server


def quantity(value):
    return {"value": value, "unit": "m", "frame": "model_local"}


def batch(runtime, request_id="plan"):
    model = runtime.model
    return {
        "protocol_version": 1,
        "request_id": request_id,
        "model_id": str(model.model_id),
        "expected_revision": model.revision,
        "commands": [{"name": "p", "operation": "create_point", "arguments": {"position": quantity((1, 2, 3))}}],
    }


def test_discovery_and_session_receipt_retry(tmp_path: Path):
    path = tmp_path / "geometry.json"
    write_geometry(path, GeometryModel())
    runtime = GeometryAutomationRuntime(path)
    assert runtime.kernel_capabilities()["result"]["protocol_version"] == 1
    planned = runtime.plan_edit(batch(runtime), session_id="a")
    plan = planned["result"]
    request = {"protocol_version": 1, "request_id": "apply", "model_id": str(runtime.model.model_id), "expected_revision": runtime.model.revision, "plan": plan, "approved": True}
    first = runtime.apply_edit(request, session_id="a")
    second = runtime.apply_edit(request, session_id="a")
    assert first == second
    assert first["ok"] is True
    # A distinct session does not inherit receipts; the now-stale revision
    # prevents a repeated edit instead.
    isolated = runtime.apply_edit(request, session_id="b")
    assert isolated["error"]["code"] == "STALE_REVISION"
    assert runtime.model.revision == 1


def test_approval_and_write_back_are_separate_boundaries(tmp_path: Path):
    path = tmp_path / "geometry.json"
    original = GeometryModel()
    write_geometry(path, original)
    runtime = GeometryAutomationRuntime(path)
    plan = runtime.plan_edit(batch(runtime))["result"]
    denied = runtime.apply_edit({"protocol_version": 1, "request_id": "no", "model_id": str(runtime.model.model_id), "expected_revision": runtime.model.revision, "plan": plan, "approved": False})
    assert denied["error"]["code"] == "APPROVAL_REQUIRED"
    disabled = runtime.apply_edit({"protocol_version": 1, "request_id": "write", "model_id": str(runtime.model.model_id), "expected_revision": runtime.model.revision, "plan": plan, "approved": True, "write_back": True})
    assert disabled["error"]["code"] == "WRITE_BACK_DISABLED"
    assert read_geometry(path).revision == original.revision

    writable = GeometryAutomationRuntime(path, allow_write_back=True)
    plan = writable.plan_edit(batch(writable, "write-plan"))["result"]
    result = writable.apply_edit({"protocol_version": 1, "request_id": "write", "model_id": str(writable.model.model_id), "expected_revision": writable.model.revision, "plan": plan, "approved": True, "write_back": True})
    assert result["ok"] is True
    restored = read_geometry(path)
    assert restored.revision == 1 and len(restored.vertices) == 1


def test_tool_input_cannot_choose_a_path(tmp_path: Path):
    path = tmp_path / "geometry.json"
    write_geometry(path, GeometryModel())
    runtime = GeometryAutomationRuntime(path)
    request = batch(runtime)
    request["path"] = str(tmp_path / "other.json")
    response = runtime.plan_edit(request)
    assert response["ok"] is False
    assert response["error"]["code"] == "UNKNOWN_FIELD"
    assert runtime.path == path.resolve()


def test_mcp_discovery_exposes_exactly_seven_tools(tmp_path: Path):
    path = tmp_path / "geometry.json"
    write_geometry(path, GeometryModel())
    server = build_server(GeometryAutomationRuntime(path))
    manager = getattr(server, "_tool_manager")
    tools = manager.list_tools()
    assert {item.name for item in tools} == {
        "kernel_capabilities",
        "model_summary",
        "select_entities",
        "describe_entities",
        "query_geometry",
        "plan_edit",
        "apply_edit",
    }


def test_restart_after_written_apply_rejects_old_plan_as_stale(tmp_path: Path):
    path = tmp_path / "geometry.json"
    write_geometry(path, GeometryModel())
    runtime = GeometryAutomationRuntime(path, allow_write_back=True)
    plan = runtime.plan_edit(batch(runtime))["result"]
    applied = runtime.apply_edit(
        {
            "protocol_version": 1,
            "request_id": "apply",
            "model_id": str(runtime.model.model_id),
            "expected_revision": runtime.model.revision,
            "plan": plan,
            "approved": True,
            "write_back": True,
        }
    )
    assert applied["ok"] is True
    restarted = GeometryAutomationRuntime(path, allow_write_back=True)
    duplicate = restarted.apply_edit(
        {
            "protocol_version": 1,
            "request_id": "apply",
            "model_id": str(restarted.model.model_id),
            "expected_revision": restarted.model.revision,
            "plan": plan,
            "approved": True,
        }
    )
    assert duplicate["error"]["code"] == "STALE_PLAN"
