word_count() {
  local text="$1"
  # Default IFS word-splitting collapses any run of whitespace; disable globbing
  # so tokens like '*' are counted literally rather than expanded.
  set -f
  set -- $text
  set +f
  echo "$#"
}
