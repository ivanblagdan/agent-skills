#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  summarize_flow_map.sh --scan-dir <path> [--output <file>] [--scope-label <text>]

Examples:
  summarize_flow_map.sh --scan-dir /abs/repo/.flow-map
  summarize_flow_map.sh --scan-dir /tmp/flow --output /tmp/flow/summary.md --scope-label "Timeline coordinator -> provider"
USAGE
}

SCAN_DIR=""
OUTPUT=""
SCOPE_LABEL=""

while (($#)); do
  case "$1" in
    --scan-dir)
      SCAN_DIR="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    --scope-label)
      SCOPE_LABEL="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$SCAN_DIR" ]]; then
  echo "error: --scan-dir is required" >&2
  usage >&2
  exit 2
fi

if [[ ! -d "$SCAN_DIR" ]]; then
  echo "error: scan dir does not exist: $SCAN_DIR" >&2
  exit 2
fi

HIGH_JSON="${SCAN_DIR}/high_signal.json"
SHAPES_JSON="${SCAN_DIR}/shapes.json"
SHORT_TXT="${SCAN_DIR}/high_signal_short.txt"
META_TXT="${SCAN_DIR}/scan_meta.txt"

if [[ ! -f "$HIGH_JSON" ]]; then
  echo "error: missing high signal artifact: $HIGH_JSON" >&2
  exit 2
fi

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="${SCAN_DIR}/flow_map_summary.md"
fi

have_jq=0
if command -v jq >/dev/null 2>&1; then
  have_jq=1
fi

high_count="unknown"
shape_count="n/a"
rule_breakdown=""
file_breakdown=""

if ((have_jq)); then
  high_count="$(jq 'length' "$HIGH_JSON")"
  if [[ -f "$SHAPES_JSON" ]]; then
    shape_count="$(jq 'length' "$SHAPES_JSON")"
  fi

  rule_breakdown="$(jq -r 'group_by(.ruleId) | sort_by(-length) | .[] | "- `\(.[0].ruleId)`: \(length)"' "$HIGH_JSON")"
  file_breakdown="$(jq -r 'group_by(.file) | sort_by(-length) | .[] | "- `\(.[0].file)`: \(length)"' "$HIGH_JSON")"
else
  high_count="(install jq for counts)"
  if [[ -f "$SHAPES_JSON" ]]; then
    shape_count="(install jq for counts)"
  fi
fi

{
  echo "# Flow Map Draft"
  echo
  if [[ -n "$SCOPE_LABEL" ]]; then
    echo "Scope: ${SCOPE_LABEL}"
    echo
  fi
  echo "## Scan Inputs"
  if [[ -f "$META_TXT" ]]; then
    echo '```text'
    cat "$META_TXT"
    echo '```'
  else
    echo "- scan metadata not found: $META_TXT"
  fi
  echo
  echo "## Inventory Snapshot"
  echo "- High-signal matches: ${high_count}"
  echo "- Shape matches: ${shape_count}"
  if [[ -f "$SHORT_TXT" ]]; then
    printf -- '- Raw short report: `%s`\n' "$SHORT_TXT"
  fi
  echo

  echo "## Rule Hits (High Signal)"
  if [[ -n "$rule_breakdown" ]]; then
    echo "$rule_breakdown"
  else
    echo "- (install jq to auto-generate counts)"
  fi
  echo

  echo "## File Hits (High Signal)"
  if [[ -n "$file_breakdown" ]]; then
    echo "$file_breakdown"
  else
    echo "- (install jq to auto-generate counts)"
  fi
  echo

  echo "## Flow Summary (5-12 Steps)"
  echo "1. [entrypoint]"
  echo "2. [transform]"
  echo "3. [I/O]"
  echo "4. [side effect]"
  echo "5. [exit]"
  echo

  echo "## Shape Map"
  echo "- Canonical shapes: [fill]"
  echo "- Boundary shapes: [fill]"
  echo "- Transforms: [fill]"
  echo "- Redundant mappings: [fill]"
  echo

  echo "## Concurrency + Hot-Path Notes"
  echo "- Concurrency boundaries: [fill]"
  echo "- Shared mutable state / contention: [fill]"
  echo "- Proven hot paths: [fill or none]"
  echo "- Suspected hot paths: [fill + heuristic]"
  echo

  echo "## Mermaid: Flowchart"
  echo '```mermaid'
  echo 'flowchart TD'
  echo '  A[Entry] --> B[Transform] --> C[I/O] --> D[Exit]'
  echo '  classDef hot fill:#ffe6e6,stroke:#ff4d4d,stroke-width:2px;'
  echo '  classDef async fill:#e6f0ff,stroke:#2f6fed,stroke-width:2px;'
  echo '  classDef boundary fill:#fff7e6,stroke:#f0a500,stroke-width:2px;'
  echo '  classDef data fill:#e6fff2,stroke:#2dbf6a,stroke-width:2px;'
  echo '  classDef io fill:#f2e6ff,stroke:#8a2be2,stroke-width:2px;'
  echo '```'
  echo

  echo "## Mermaid: Sequence"
  echo '```mermaid'
  echo 'sequenceDiagram'
  echo '  participant Entry'
  echo '  participant Worker'
  echo '  participant IO as I/O'
  echo '  Entry->>Worker: start'
  echo '  par async branch'
  echo '    Worker->>IO: request'
  echo '  and async branch'
  echo '    Worker->>Worker: transform'
  echo '  end'
  echo '  Worker-->>Entry: complete'
  echo '```'
} > "$OUTPUT"

echo "summary scaffold written: $OUTPUT"
