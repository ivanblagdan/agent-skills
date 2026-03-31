#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  export_mermaid_png.sh [options] -- <report.md>

This script renders Mermaid diagrams embedded in a Markdown report and writes:
- a rendered Markdown file with image links
- image artifacts (PNG by default)

Options:
  --report <path>           Markdown report containing Mermaid code blocks.
                            You can also pass this as the single positional argument after `--`.
  --output <path>           Rendered markdown output path.
                            Default: <report-dir>/<report-stem>.rendered.md
  --out-dir <path>          Diagram artifacts directory.
                            Alias: --artefacts-dir
                            Default: <output-dir>/artefacts
  --artefacts-dir <path>    Same as --out-dir.
  --format <fmt>            Diagram image format for markdown extraction.
                            Choices: png|svg|pdf (default: png)
  --theme <name>            Mermaid theme (default: dark)
  --background <color>      Background color for png/svg (default: black)
  --mmdc <path>             Mermaid CLI binary (default: mmdc)
  --config <path>           Puppeteer config file, passed to mmdc -p
  --mermaid-config <path>   Mermaid config JSON, passed to mmdc -c
  --width <px>              Width passed to mmdc -w
  --height <px>             Height passed to mmdc -H
  --scale <factor>          Scale passed to mmdc -s
  -h, --help                Show this help message

Examples:
  export_mermaid_png.sh \
    --out-dir /abs/repo/.flow-map/artefacts \
    --output /abs/repo/.flow-map/flow_map.rendered.md \
    -- /abs/repo/.flow-map/flow_map.md

  export_mermaid_png.sh \
    --theme neutral \
    --background transparent \
    --format png \
    -- /abs/repo/.flow-map/flow_map.md
USAGE
}

INPUT_MD=""
OUTPUT_MD=""
ARTEFACTS_DIR=""
THEME="dark"
BACKGROUND="black"
FORMAT="png"
MMDC_BIN="mmdc"
PUPPETEER_CONFIG=""
MERMAID_CONFIG=""
WIDTH=""
HEIGHT=""
SCALE="2"
POSITIONAL=()

while (($#)); do
  case "$1" in
    --report)
      INPUT_MD="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT_MD="${2:-}"
      shift 2
      ;;
    --out-dir|--artefacts-dir)
      ARTEFACTS_DIR="${2:-}"
      shift 2
      ;;
    --format|--output-format)
      FORMAT="${2:-}"
      shift 2
      ;;
    --theme)
      THEME="${2:-}"
      shift 2
      ;;
    --background)
      BACKGROUND="${2:-}"
      shift 2
      ;;
    --mmdc)
      MMDC_BIN="${2:-}"
      shift 2
      ;;
    --config)
      PUPPETEER_CONFIG="${2:-}"
      shift 2
      ;;
    --mermaid-config)
      MERMAID_CONFIG="${2:-}"
      shift 2
      ;;
    --width)
      WIDTH="${2:-}"
      shift 2
      ;;
    --height)
      HEIGHT="${2:-}"
      shift 2
      ;;
    --scale)
      SCALE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while (($#)); do
        POSITIONAL+=("$1")
        shift
      done
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$INPUT_MD" ]]; then
  if ((${#POSITIONAL[@]} == 1)); then
    INPUT_MD="${POSITIONAL[0]}"
  elif ((${#POSITIONAL[@]} == 0)); then
    echo "error: markdown report input is required" >&2
    usage >&2
    exit 2
  else
    echo "error: expected exactly one markdown report input, got ${#POSITIONAL[@]}" >&2
    usage >&2
    exit 2
  fi
elif ((${#POSITIONAL[@]} > 0)); then
  echo "error: received positional inputs in addition to --report" >&2
  usage >&2
  exit 2
fi

if [[ ! -f "$INPUT_MD" ]]; then
  echo "error: input report does not exist: $INPUT_MD" >&2
  exit 2
fi

if [[ "${INPUT_MD##*.}" != "md" ]]; then
  echo "error: input must be a markdown file (.md): $INPUT_MD" >&2
  exit 2
fi

if ! command -v "$MMDC_BIN" >/dev/null 2>&1; then
  echo "error: mmdc binary not found: $MMDC_BIN" >&2
  exit 2
fi

if [[ -z "$OUTPUT_MD" ]]; then
  base_name="$(basename "$INPUT_MD")"
  stem="${base_name%.*}"
  OUTPUT_MD="$(dirname "$INPUT_MD")/${stem}.rendered.md"
fi

if [[ -z "$ARTEFACTS_DIR" ]]; then
  ARTEFACTS_DIR="$(dirname "$OUTPUT_MD")/artefacts"
fi

mkdir -p "$(dirname "$OUTPUT_MD")"
mkdir -p "$ARTEFACTS_DIR"

case "$FORMAT" in
  png|svg|pdf) ;;
  *)
    echo "error: unsupported format '$FORMAT' (expected: png, svg, pdf)" >&2
    exit 2
    ;;
esac

cmd=(
  "$MMDC_BIN"
  -i "$INPUT_MD"
  -o "$OUTPUT_MD"
  -a "$ARTEFACTS_DIR"
  -e "$FORMAT"
  -t "$THEME"
  -b "$BACKGROUND"
)

if [[ -n "$MERMAID_CONFIG" ]]; then
  cmd+=( -c "$MERMAID_CONFIG" )
fi
if [[ -n "$PUPPETEER_CONFIG" ]]; then
  cmd+=( -p "$PUPPETEER_CONFIG" )
fi
if [[ -n "$WIDTH" ]]; then
  cmd+=( -w "$WIDTH" )
fi
if [[ -n "$HEIGHT" ]]; then
  cmd+=( -H "$HEIGHT" )
fi
if [[ -n "$SCALE" ]]; then
  cmd+=( -s "$SCALE" )
fi

"${cmd[@]}"

echo "rendered markdown: $OUTPUT_MD"
echo "diagram artifacts: $ARTEFACTS_DIR"
