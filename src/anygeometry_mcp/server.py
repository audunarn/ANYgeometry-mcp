"""stdio MCP entry point exposing exactly seven stable tools."""

from __future__ import annotations

import argparse
from typing import Any

from .runtime import GeometryAutomationRuntime


def build_server(runtime: GeometryAutomationRuntime):
    """Create the official MCP SDK v2 server lazily.

    Keeping this import out of :mod:`runtime` makes the receipt and write-back
    boundary testable without importing the transport SDK.
    """

    try:
        from mcp.server import MCPServer
    except ImportError:  # MCP SDK 1.x compatibility for existing hosts.
        from mcp.server.fastmcp import FastMCP as MCPServer

    server = MCPServer(
        "ANYgeometry",
        instructions=(
            "Use the provider-neutral protocol. Inspect/select first, plan every "
            "mutation, present the preview, and call apply_edit only after approval."
        ),
    )

    @server.tool()
    def kernel_capabilities(request_id: str = "kernel_capabilities") -> dict[str, Any]:
        return runtime.kernel_capabilities(request_id)

    @server.tool()
    def model_summary(request: dict[str, Any]) -> dict[str, Any]:
        return runtime.model_summary(request)

    @server.tool()
    def select_entities(request: dict[str, Any]) -> dict[str, Any]:
        return runtime.select_entities(request)

    @server.tool()
    def describe_entities(request: dict[str, Any]) -> dict[str, Any]:
        return runtime.describe_entities(request)

    @server.tool()
    def query_geometry(request: dict[str, Any]) -> dict[str, Any]:
        return runtime.query_geometry(request)

    @server.tool()
    def plan_edit(request: dict[str, Any]) -> dict[str, Any]:
        return runtime.plan_edit(request, session_id="stdio")

    @server.tool()
    def apply_edit(request: dict[str, Any]) -> dict[str, Any]:
        return runtime.apply_edit(request, session_id="stdio")

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve one ANYgeometry document over MCP stdio")
    parser.add_argument("geometry", help="explicit geometry JSON or gzip document")
    parser.add_argument("--allow-write-back", action="store_true", help="permit explicit write_back=true to the startup path")
    args = parser.parse_args(argv)
    runtime = GeometryAutomationRuntime(args.geometry, allow_write_back=args.allow_write_back)
    build_server(runtime).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
