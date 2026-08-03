#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/smart-money-decoder-build.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT

cd "$repo_dir"

python_bin=python3
if [ -x .venv/bin/python ]; then
  python_bin=.venv/bin/python
fi

for test_file in tests/test_*.py; do
  "$python_bin" "$test_file"
done

cd frontend
npm run build -- --outDir "$build_dir" --emptyOutDir
