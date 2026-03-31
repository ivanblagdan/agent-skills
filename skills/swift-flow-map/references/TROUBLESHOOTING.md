# swift-flow-map troubleshooting

## 1) `Cannot read rule directory ...`
Cause:
- `sgconfig.yml` points to the wrong `ruleDirs` path.

Fix:
- In this skill, use:

```yaml
ruleDirs:
  - ast-grep-rules/
```

- Run with explicit config path:

```bash
ast-grep scan --config /abs/path/to/swift-flow-map/sgconfig.yml /abs/project
```

## 2) `Cannot parse rule ... Multiple AST nodes are detected`
Cause:
- Some multiline `pattern: |` blocks in Swift rules can fail parse depending on pattern shape.

Fix:
- Prefer single-line quoted patterns where possible:

```yaml
pattern: "Task { $$$BODY }"
pattern: "actor $NAME { $$$BODY }"
```

## 3) Duplicate/noisy matches
Cause:
- Overlapping rules (e.g., two task-creation rules that match the same node).

Fix:
- Keep one canonical rule per concept.
- Or run with `--filter` for high-signal subsets.

## 4) Too many results (token-heavy)
Cause:
- Full-shape discovery over large scope.

Fix:
- Use two-pass scan:
1. High signal only: `swift.(concurrency|boundary|io|hot).*`
2. Shapes only when needed.

- Use compact JSON artifacts and summarize from files.

## 5) No matches where you expect some
Cause:
- Scope path is wrong or too narrow.
- Rule is valid but pattern does not match current syntax shape.

Fix:
- Verify absolute scope paths.
- Check file-level run first:

```bash
ast-grep scan --config /abs/sgconfig.yml /abs/file.swift --report-style short
```

- If still missing, debug with MCP tools:
  - `dump_syntax_tree`
  - `test_match_code_rule`

## 6) CLI works but MCP inline rules fail
Cause:
- YAML or quoting differences in inline payload.

Fix:
- Keep rules in files and run CLI for baseline.
- Use MCP only for targeted deep dives/debugging.
