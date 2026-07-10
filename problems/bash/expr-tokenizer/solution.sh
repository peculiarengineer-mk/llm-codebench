tokenize() {
  local expr="$1"
  local n=${#expr}
  local i=0 c num=""

  while [ "$i" -lt "$n" ]; do
    c="${expr:$i:1}"
    case "$c" in
      [0-9])
        num="$num$c"
        ;;
      ' ' | $'\t')
        if [ -n "$num" ]; then echo "$num"; num=""; fi
        ;;
      '+' | '-' | '*' | '/' | '(' | ')')
        if [ -n "$num" ]; then echo "$num"; num=""; fi
        echo "$c"
        ;;
      *)
        echo "tokenize: unexpected character '$c'" >&2
        return 1
        ;;
    esac
    i=$((i + 1))
  done

  if [ -n "$num" ]; then echo "$num"; fi
  return 0
}
