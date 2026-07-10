set -euo pipefail

source ./solution.sh

assert_eq() {  # assert_eq <got> <want> <msg>
  if [ "$1" != "$2" ]; then
    echo "FAIL $3: got '$1', want '$2'" >&2
    exit 1
  fi
}

assert_eq "$(tokenize "12+3 * (4-5)")" \
  "$(printf '12\n+\n3\n*\n(\n4\n-\n5\n)')" "full"
assert_eq "$(tokenize "1+2")" "$(printf '1\n+\n2')" "simple"
assert_eq "$(tokenize "42")" "42" "single-number"
assert_eq "$(tokenize "1000")" "1000" "multi-digit"
assert_eq "$(tokenize "")" "" "empty"
assert_eq "$(tokenize "   ")" "" "whitespace-only"
assert_eq "$(tokenize "(((7)))")" "$(printf '(\n(\n(\n7\n)\n)\n)')" "nested-parens"

# Invalid characters must yield a non-zero exit status. A failing command in an
# `if` condition does not trip `set -e`, so this is a safe way to assert failure.
if tokenize "1+a" >/dev/null 2>&1; then
  echo "FAIL invalid-char: expected non-zero exit" >&2
  exit 1
fi

echo "ok"
