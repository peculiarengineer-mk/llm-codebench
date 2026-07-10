sum_column() {
  local csv="$1" col="$2"
  # awk fields are 1-based; skip blank lines so a trailing newline adds nothing.
  printf '%s\n' "$csv" | awk -F, -v c="$((col + 1))" '
    NF && $0 != "" { s += $c }
    END { print s + 0 }
  '
}
