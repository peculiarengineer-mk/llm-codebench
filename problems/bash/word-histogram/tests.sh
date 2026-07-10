set -euo pipefail

source ./solution.sh

assert_eq() {  # assert_eq <got> <want> <msg>
  if [ "$1" != "$2" ]; then
    echo "FAIL $3: got '$1', want '$2'" >&2
    exit 1
  fi
}

assert_eq "$(histogram "a b a c b a")" "$(printf 'a: 3\nb: 2\nc: 1')" "basic"
assert_eq "$(histogram "one")" "one: 1" "single"
assert_eq "$(histogram "")" "" "empty"
assert_eq "$(histogram "   ")" "" "all-whitespace"
# Ties on count 1 break alphabetically ascending.
assert_eq "$(histogram "pear apple pear banana")" \
  "$(printf 'pear: 2\napple: 1\nbanana: 1')" "tie-break"
# Multiple/leading whitespace is collapsed.
assert_eq "$(histogram "  go   go  stop ")" "$(printf 'go: 2\nstop: 1')" "spacing"

echo "ok"
