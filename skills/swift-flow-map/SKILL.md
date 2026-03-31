---
name: swift-flow-map
description: Build a Swift data-flow + shape map with Mermaid diagrams. Highlight concurrency boundaries and suspected hot paths. Uses ast-grep (and its MCP) for structural search. Use when asked about data flow, shape transformations, or concurrency in Swift codebases.
---

# swift-flow-map

## Preconditions
- Do not modify product code. This skill is analysis-only.
- `ast-grep` (v0.41.0) CLI must be available for scan mode.
- `mmdc` (Mermaid CLI) must be available for diagram rendering.
- The `ast-grep` MCP server should be available for targeted deep-dive/debug mode (`dump_syntax_tree`, `find_code`, `find_code_by_rule`, `test_match_code_rule`).

## Inputs
- Scope: entrypoint(s) / feature name / key files / endpoint(s).
  - If missing, infer a minimal scope and state assumptions.

## Required outputs
Follow: `references/FLOW_MAP_CONTRACT.md`

## Workflow

### 0) Resolve absolute project path
- Determine repo root (for example: `git rev-parse --show-toplevel`).
- Use absolute paths for all scan inputs.

### 1) Run high-signal scan (CLI first)
Use script:

```bash
scripts/scan_flow_map.sh --project-root <abs-project-root> -- <targets...>
```

Notes:
- This emits compact artifacts in `<project>/.data-flow/` by default.
- High-signal scan includes concurrency + boundary + I/O + hot-suspect rules.
- Add `--include-shapes` only when shape discovery is required.

### 2) Generate contract-oriented scaffold
Use script:

```bash
scripts/summarize_flow_map.sh --scan-dir <abs-scan-dir> --scope-label "<scope label>"
```

This produces a markdown scaffold with:
- inventory snapshot
- rule/file hit breakdown (when `jq` is available)
- required contract sections ready to fill

### 3) Use MCP only for targeted deep dives
Use MCP when you need precision or rule debugging:
- `find_code_by_rule` for focused extraction
- `dump_syntax_tree` when rule matching is ambiguous
- `test_match_code_rule` to validate/refine patterns

### 4) Synthesize the flow
- Start from entrypoint(s): `entry -> transforms -> I/O -> side effects -> exit`.
- Mark uncertainty explicitly where call graph edges are inferred.
- Collapse helper noise unless it is a concurrency, boundary, or hot-path node.

### 5) Report
Ask the user if they want a full report with rendered diagrams, and where they would like it saved (suggest `<abs-scan-dir>/data-flow/<report-name>/` by default).

**Create a final report in markdown with embedded Mermaid diagrams:**
- Include class defs from `references/MERMAID_STYLE.md`.
- Flowchart:
  - nodes for entry, transforms, I/O, canonical shapes
  - classes: `async`, `boundary`, `hot`, `data`, `io`
- Sequence diagram:
  - emphasize task/actor/queue hops
  - use `par` for parallel work
- Embed each diagram directly in the report using Mermaid Markdown blocks (no separate `.mmd` files unless explicitly requested).

**Render report markdown + PNG artifacts with Mermaid CLI (`mmdc`)**
Use script (with escalated permissions):

```bash
scripts/export_mermaid_png.sh \
  --out-dir <abs-scan-dir>/artefacts \
  --output <abs-scan-dir>/<report-name>.rendered.md \
  -- <abs-scan-dir>/<report-name>.md
```

## Troubleshooting
- See: `references/TROUBLESHOOTING.md`
- `mmdc` parse errors usually mean invalid Mermaid syntax in report diagram blocks.
