"""Release-graph checks for the source-only MCP adapter."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_geometry_dependency_tracks_the_coordinated_candidate() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["name"] == "ANYgeometry-mcp"
    assert project["dependencies"] == [
        "ANYgeometry>=0.4.1,<0.5",
        "mcp>=2,<3",
    ]
    assert "ANYgeometry>=0.4.1,<0.5" in (ROOT / "README.md").read_text(
        encoding="utf-8"
    )
