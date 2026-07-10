# Word count

Define a shell function `word_count` that takes a single string argument and
echoes the number of whitespace-separated words it contains.

```
word_count "the quick brown fox"   ->  4
word_count "  spaced   out  "       ->  2
word_count ""                        ->  0
```

Words are separated by any run of whitespace. An empty (or all-whitespace)
string has zero words.
