set -euo pipefail

source ./solution.sh

assert_eq() {  # assert_eq <got> <want> <msg>
  if [ "$1" != "$2" ]; then
    echo "FAIL $3: got '$1', want '$2'" >&2
    exit 1
  fi
}

assert_eq "$(sum_column $'1,2,3\n4,5,6' 0)" "5" "col0"
assert_eq "$(sum_column $'1,2,3\n4,5,6' 1)" "7" "col1"
assert_eq "$(sum_column $'1,2,3\n4,5,6' 2)" "9" "col2"
assert_eq "$(sum_column '' 0)" "0" "empty"
assert_eq "$(sum_column '42' 0)" "42" "single-cell"
assert_eq "$(sum_column $'10,1\n-4,2\n-6,3' 0)" "0" "negatives"
assert_eq "$(sum_column $'1,2\n3,4\n5,6\n7,8' 1)" "20" "many-rows"

echo "ok"
