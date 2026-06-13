#!/usr/bin/env bash

set -euo pipefail

if ! command -v d2 >/dev/null 2>&1; then
  echo "error: d2 is not installed or not on PATH" >&2
  echo "install: brew install d2" >&2
  exit 1
fi

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: ./scripts/render_d2.sh <input.d2> [output.svg]" >&2
  exit 1
fi

input_path="$1"
if [[ ! -f "$input_path" ]]; then
  echo "error: input file not found: $input_path" >&2
  exit 1
fi

output_path="${2:-${input_path%.d2}.svg}"
if [[ "$output_path" == "$input_path" ]]; then
  echo "error: output path must be different from input path" >&2
  exit 1
fi

d2_debug="${DEBUG:-}"
case "$d2_debug" in
  ""|0|1|true|false) ;;
  *) d2_debug=false ;;
esac

mkdir -p "$(dirname "$output_path")"
DEBUG="$d2_debug" d2 "$input_path" "$output_path"
echo "rendered: $output_path"
