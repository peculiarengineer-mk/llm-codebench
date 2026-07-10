set -euo pipefail

source ./solution.sh

assert_eq() {  # assert_eq <got> <want> <msg>
  if [ "$1" != "$2" ]; then
    echo "FAIL $3: got '$1', want '$2'" >&2
    exit 1
  fi
}

assert_eq "$(word_count "the quick brown fox")" "4" "basic"
assert_eq "$(word_count "  spaced   out  ")" "2" "extra-whitespace"
assert_eq "$(word_count "")" "0" "empty"
assert_eq "$(word_count "     ")" "0" "all-whitespace"
assert_eq "$(word_count "single")" "1" "single"
assert_eq "$(word_count "a b c d e f g")" "7" "many"

echo "ok"
