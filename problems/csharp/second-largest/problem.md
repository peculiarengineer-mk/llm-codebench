# Second largest

Inside `namespace Grok;`, expose a `public static class Solver` with the method:

```csharp
public static int SecondLargest(int[] xs)
```

It returns the second largest **distinct** value in `xs`. Duplicates of the
maximum do not count, e.g. `SecondLargest([5, 5, 4])` is `4`. You may assume
`xs` contains at least two distinct values.

```
SecondLargest([1, 2, 3])       ->  2
SecondLargest([10, 10, 9, 9])  ->  9
```
