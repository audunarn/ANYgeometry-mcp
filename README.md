# ANYgeometry MCP

Reference stdio MCP adapter for `ANYgeometry>=0.3,<0.4`. The adapter exposes
the kernel's provider-neutral automation protocol; it does not interpret
natural language and never executes generated Python.

```powershell
anygeometry-mcp C:\models\structure.anygeometry.json
anygeometry-mcp C:\models\structure.anygeometry.json --allow-write-back
```

The geometry path is supplied only at process startup. Tool arguments cannot
select another path. `apply_edit` requires `approved=true`; saving additionally
requires startup `--allow-write-back` and per-call `write_back=true`. Saving is
never automatic.

The seven tools are `kernel_capabilities`, `model_summary`, `select_entities`,
`describe_entities`, `query_geometry`, `plan_edit`, and `apply_edit`.

