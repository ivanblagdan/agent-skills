#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scan_flow_map.sh --project-root <absolute-path> [--out-dir <path>] [--include-shapes] [-- <targets...>]

Examples:
  scan_flow_map.sh --project-root /abs/repo
  scan_flow_map.sh --project-root /abs/repo --out-dir /tmp/flow-map -- Apps/App.swift Packages/Kit/Sources
USAGE
}

PROJECT_ROOT=""
OUT_DIR=""
INCLUDE_SHAPES=0
TARGETS=()

while (($#)); do
  case "$1" in
    --project-root)
      PROJECT_ROOT="${2:-}"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --include-shapes)
      INCLUDE_SHAPES=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      while (($#)); do
        TARGETS+=("$1")
        shift
      done
      ;;
    *)
      TARGETS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "error: --project-root is required" >&2
  usage >&2
  exit 2
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "error: project root does not exist: $PROJECT_ROOT" >&2
  exit 2
fi

if [[ "$PROJECT_ROOT" != /* ]]; then
  echo "error: --project-root must be an absolute path" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${SKILL_ROOT}/sgconfig.yml"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "error: missing config: $CONFIG_PATH" >&2
  exit 2
fi

if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="${PROJECT_ROOT}/.flow-map"
fi
mkdir -p "$OUT_DIR"

if ((${#TARGETS[@]} == 0)); then
  TARGETS=("$PROJECT_ROOT")
fi

HIGH_SIGNAL_FILTER='^swift\.(concurrency|boundary|io|hot)\.'
SHAPES_FILTER='^swift\.shape\.'

HIGH_SIGNAL_JSON="${OUT_DIR}/high_signal.json"
SHAPES_JSON="${OUT_DIR}/shapes.json"
RAW_SHORT_TXT="${OUT_DIR}/high_signal_short.txt"
META_TXT="${OUT_DIR}/scan_meta.txt"

ast-grep scan \
  --config "$CONFIG_PATH" \
  --filter "$HIGH_SIGNAL_FILTER" \
  --json=compact \
  "${TARGETS[@]}" \
  > "$HIGH_SIGNAL_JSON"

ast-grep scan \
  --config "$CONFIG_PATH" \
  --filter "$HIGH_SIGNAL_FILTER" \
  --report-style short \
  "${TARGETS[@]}" \
  > "$RAW_SHORT_TXT"

if ((INCLUDE_SHAPES)); then
  ast-grep scan \
    --config "$CONFIG_PATH" \
    --filter "$SHAPES_FILTER" \
    --json=compact \
    "${TARGETS[@]}" \
    > "$SHAPES_JSON"
fi

{
  echo "timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "project_root: $PROJECT_ROOT"
  echo "config: $CONFIG_PATH"
  echo "targets:"
  for target in "${TARGETS[@]}"; do
    echo "  - $target"
  done
  echo "high_signal_json: $HIGH_SIGNAL_JSON"
  echo "high_signal_short: $RAW_SHORT_TXT"
  if ((INCLUDE_SHAPES)); then
    echo "shapes_json: $SHAPES_JSON"
  fi
} > "$META_TXT"

echo "flow-map scan complete"
echo "  high signal json: $HIGH_SIGNAL_JSON"
echo "  high signal short: $RAW_SHORT_TXT"
if ((INCLUDE_SHAPES)); then
  echo "  shapes json: $SHAPES_JSON"
fi
echo "  metadata: $META_TXT"
