# mergeset.stacks

Stacked changes: when the candidates are not independent.

A pull request opened against another pull request’s branch already *contains*
it. That single fact breaks the assumption that any subset of the candidates is
a meaningful thing to evaluate, and it breaks it in three places at once:

- **Validity.** Asking for `{616}` when 616 is stacked on 604 on 587 really
  means `{587, 604, 616}`. A valid set must be **downward-closed** under the
  parent relation. Note “downward-closed in a forest”, not “a prefix of a
  chain”: stacks branch, so two changes can be siblings on the same parent.
- **Cost.** Merging a stack’s tip brings every ancestor with it, so merging the
  ancestors explicitly is wasted work and can perturb merge order. Reduce a set
  to its **tips** before merging.
- **Weight.** Dropping a change drops its whole descendant cone. Weighting
  changes independently lets a hitting set cheerfully discard thousands of lines
  while believing it discarded one small PR.

Discovering the relation is [`mergeset.sources.detect_stacks()`](mergeset.sources.md#mergeset.sources.detect_stacks); acting on it
is here. The dependency map is always `child -> parent`.

### Module Attributes

| [`Dependencies`](#mergeset.stacks.Dependencies)   | `child -> parent`.   |
|-----------------------------------------------------------------|----------------------|

### Functions

| [`ancestors`](#mergeset.stacks.ancestors)(change, parents)             | Every change `change` is stacked on, transitively.                          |
|-----------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`close_down`](#mergeset.stacks.close_down)(subset, parents)            | Add every ancestor, so the set becomes a valid thing to ask for.            |
| [`close_up`](#mergeset.stacks.close_up)(subset, parents)              | Add every descendant — what dropping these changes actually costs.          |
| [`cone_weights`](#mergeset.stacks.cone_weights)(weights, parents)         | Re-weight each change by the cost of dropping its whole descendant cone.    |
| [`count_closed_subsets`](#mergeset.stacks.count_closed_subsets)(parents, changes) | How many downward-closed subsets exist — the size of the real search space. |
| [`descendants`](#mergeset.stacks.descendants)(change, parents)           | Every change stacked on `change`, transitively — its *cone*.                |
| [`largest_closed_subset`](#mergeset.stacks.largest_closed_subset)(subset, parents) | Drop members whose ancestors are missing — the set you can actually merge.  |
| [`stack_roots`](#mergeset.stacks.stack_roots)(parents, changes)          | Group changes into stacks (connected components of the parent relation).    |
| [`tips`](#mergeset.stacks.tips)(subset, parents)                  | The members of `subset` that nothing else in `subset` is stacked on.        |

### mergeset.stacks.Dependencies

`child -> parent`. A change absent from the mapping has no parent.

alias of [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.stacks.ancestors(change, parents)

Every change `change` is stacked on, transitively.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(ancestors('c', {'c': 'b', 'b': 'a'}))
('a', 'b')
```

### mergeset.stacks.close_down(subset, parents)

Add every ancestor, so the set becomes a valid thing to ask for.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(close_down({'c'}, {'c': 'b', 'b': 'a'}))
('a', 'b', 'c')
```

### mergeset.stacks.close_up(subset, parents)

Add every descendant — what dropping these changes actually costs.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(close_up({'a'}, {'c': 'b', 'b': 'a'}))
('a', 'b', 'c')
```

### mergeset.stacks.cone_weights(weights, parents)

Re-weight each change by the cost of dropping its whole descendant cone.

Dropping a stack’s root drops the stack. The hitting set has to know that,
or it will pick the “cheapest” change and take eight thousand lines with it.

* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

```pycon
>>> cone_weights({'a': 1.0, 'b': 2.0}, {'b': 'a'})
{'a': 3.0, 'b': 2.0}
```

### mergeset.stacks.count_closed_subsets(parents, changes)

How many downward-closed subsets exist — the size of the real search space.

Worth reporting: on a 15-change forest of four stacks this is 576 rather
than 32768, which is the difference between “enumerate carefully” and
“hopeless”.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

```pycon
>>> count_closed_subsets({'b': 'a'}, ['a', 'b'])
3
```

### mergeset.stacks.descendants(change, parents)

Every change stacked on `change`, transitively — its *cone*.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(descendants('a', {'c': 'b', 'b': 'a', 'd': 'a'}))
('b', 'c', 'd')
```

### mergeset.stacks.largest_closed_subset(subset, parents)

Drop members whose ancestors are missing — the set you can actually merge.

This is the *other* way to make a set valid, and it is the one the solver
needs: when the search decides to drop a parent, the descendants have to go
too, and no amount of wanting them back changes that.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(largest_closed_subset({'b', 'c'}, {'c': 'b', 'b': 'a'}))
()
>>> set_key(largest_closed_subset({'a', 'b', 'd'}, {'c': 'b', 'b': 'a'}))
('a', 'b', 'd')
```

### mergeset.stacks.stack_roots(parents, changes)

Group changes into stacks (connected components of the parent relation).

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

```pycon
>>> [set_key(g) for g in stack_roots({'b': 'a', 'd': 'c'}, 'abcde')]
[('a', 'b'), ('c', 'd'), ('e',)]
```

### mergeset.stacks.tips(subset, parents)

The members of `subset` that nothing else in `subset` is stacked on.

Merging these brings the rest along for free.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(tips({'a', 'b', 'c'}, {'c': 'b', 'b': 'a'}))
('c',)
>>> set_key(tips({'a', 'b', 'd'}, {'b': 'a', 'd': 'a'}))
('b', 'd')
```
