# Word-frequency histogram

Define a shell function `histogram` that takes a single string argument and
echoes a frequency table of its whitespace-separated words, one word per line in
the form `word: count`.

Order the lines by **descending count**; break ties by the word in **ascending
alphabetical** order.

```
histogram "a b a c b a"
```
produces
```
a: 3
b: 2
c: 1
```

An empty (or all-whitespace) string produces no output.
