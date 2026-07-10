histogram() {
  local text="$1"
  # One word per line, tally, then sort by count desc (-k1nr) with alphabetical
  # tie-break (-k2), and format. LC_ALL=C keeps the alphabetical order stable.
  printf '%s\n' "$text" \
    | awk '{ for (i = 1; i <= NF; i++) print $i }' \
    | LC_ALL=C sort \
    | uniq -c \
    | LC_ALL=C sort -k1,1nr -k2,2 \
    | awk '{ print $2 ": " $1 }'
}
