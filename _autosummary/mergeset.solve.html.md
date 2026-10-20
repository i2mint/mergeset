# mergeset.solve

The search: from expensive yes/no evaluations to maximal good sets.

Vocabulary (standard in the MUS/MSS literature):

- a **conflict** is a minimal *bad* set (an MUS): remove any member and it stops
  being bad;
- a **maximal good set** is a good set that cannot be grown (an MSS);
- by Reiter’s hitting-set duality, the complement of a maximal good set is
  exactly a minimal hitting set of the conflicts.

So the loop is: propose the complement of the cheapest minimal hitting set of
the conflicts known so far; evaluate it; if it fails, shrink the failure to a
new conflict (QuickXplain) and propose again; if it passes, it is a maximal good
set — record it and ask for the next-cheapest hitting set.

Nothing here knows about git. The only thing it needs is `evaluate(subset) ->
Evaluation`, which is why the whole package is testable without a repository.

### Functions

| [`combine_components`](#mergeset.solve.combine_components)(per_component)                  | Cartesian-combine per-component maximal sets into global ones.             |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`find_maximal_good_sets`](#mergeset.solve.find_maximal_good_sets)(changes, evaluate, \*)      | Enumerate maximal good subsets of `changes`, cheapest-dropped first.       |
| [`independent_components`](#mergeset.solve.independent_components)(changes, files_of)          | Split changes into groups that cannot possibly interact via files.         |
| [`minimal_hitting_sets`](#mergeset.solve.minimal_hitting_sets)(conflicts, \*[, weight, ...]) | Yield minimal hitting sets of `conflicts`, cheapest total weight first.    |
| [`quickxplain`](#mergeset.solve.quickxplain)(evaluate, candidates, \*[, ...])       | Shrink a known-bad set to one minimal conflict, in O(k log n) evaluations. |
| [`shrink_linear`](#mergeset.solve.shrink_linear)(evaluate, candidates, \*[, ...])     | One-at-a-time conflict shrinking: `n` evaluations, dead simple.            |

### Classes

| [`SearchState`](#mergeset.solve.SearchState)([conflicts, maximal_good_sets, ...])   | Everything the search accumulated.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------|

### *class* mergeset.solve.SearchState(conflicts=list(), maximal_good_sets=list(), evaluations=0, elapsed=0.0, exhausted=False, stopped_because='', error='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Everything the search accumulated. Derived entirely from the log.

#### add_conflict(conflict)

Add `conflict`, keeping the list free of non-minimal members.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### error *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

Set when an evaluation could not be performed at all. The results below
are not wrong so much as unfinished, and must not be presented as an
answer: “we could not run the experiment” is not “the experiment failed”.

### mergeset.solve.combine_components(per_component)

Cartesian-combine per-component maximal sets into global ones.

```pycon
>>> [set_key(s) for s in combine_components([[frozenset('a')], [frozenset('c')]])]
[('a', 'c')]
```

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

### mergeset.solve.find_maximal_good_sets(changes, evaluate, \*, known_conflicts=(), depends_on=None, weight=None, max_evaluations=None, max_seconds=None, max_sets=None, shrink=<function quickxplain>, suspects=None, on_event=None)

Enumerate maximal good subsets of `changes`, cheapest-dropped first.

* **Parameters:**
  * **changes** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The change ids in play.
  * **evaluate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]) – The (cached, log-backed) oracle.
  * **known_conflicts** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflicts already known for free — e.g. textual
    `git merge-tree` conflicts and singletons whose own CI is red.
    These cost zero evaluations and prune enormously.
  * **depends_on** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `child -> parent` for stacked changes. When given, only
    downward-closed sets are ever proposed (a change is never evaluated
    without the changes it is built on) and dropping a change implicitly
    drops everything stacked on it. See [`mergeset.stacks`](mergeset.stacks.html.md#module-mergeset.stacks).
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `id -> cost of dropping it`. Higher means “keep me”.
  * **max_evaluations** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budgets. Whichever trips first
    stops the search; partial results are always returned.
  * **max_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Budgets. Whichever trips first
    stops the search; partial results are always returned.
  * **max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budgets. Whichever trips first
    stops the search; partial results are always returned.
  * **shrink** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflict-minimization strategy ([`quickxplain()`](#mergeset.solve.quickxplain) by default).
  * **suspects** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]]) – `(failed evaluation, the set) -> the changes it implicates`.
    Lets the search shrink within the implicated changes instead of
    halving the whole set. A wrong hint costs one wasted check and then
    falls back; see [`mergeset.attribution`](mergeset.attribution.html.md#module-mergeset.attribution).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – `(event_name, payload)` progress callback.
* **Return type:**
  [`SearchState`](#mergeset.solve.SearchState)
* **Returns:**
  A [`SearchState`](#mergeset.solve.SearchState). `exhausted` says whether the answer is
  complete or merely the best found within budget.

```pycon
>>> bad = [{'a', 'c'}]
>>> def ev(s):
...     ok = not any(p <= set(s) for p in bad)
...     return Evaluation(s, Verdict.PASS if ok else Verdict.FAIL)
>>> state = find_maximal_good_sets(['a', 'b', 'c'], ev)
>>> [set_key(s) for s in state.maximal_good_sets]
[('a', 'b'), ('b', 'c')]
>>> [set_key(c) for c in state.conflicts]
[('a', 'c')]
```

### mergeset.solve.independent_components(changes, files_of)

Split changes into groups that cannot possibly interact via files.

Two changes touching disjoint file sets cannot conflict textually, and (as a
working assumption worth stating out loud) rarely conflict semantically.
Connected components of the file-overlap graph are therefore independent
subproblems: solve each separately and combine the answers freely, which
turns one `2**n` search into several much smaller ones.

```pycon
>>> files = {'a': ['x.py'], 'b': ['x.py'], 'c': ['y.py']}
>>> [set_key(g) for g in independent_components(files, files.get)]
[('a', 'b'), ('c',)]
```

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

### mergeset.solve.minimal_hitting_sets(conflicts, , weight=None, limit=None)

Yield minimal hitting sets of `conflicts`, cheapest total weight first.

A hitting set touches every conflict; its complement is therefore a set with
no known conflict inside it. Enumerating hitting sets cheapest-first means
the solver proposes dropping the *least valuable* changes first.

```pycon
>>> hs = minimal_hitting_sets([frozenset({'a', 'b'}), frozenset({'b', 'c'})])
>>> [sorted(h) for h in itertools.islice(hs, 3)]
[['b'], ['a', 'c']]
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

### mergeset.solve.quickxplain(evaluate, candidates, , background=frozenset({}))

Shrink a known-bad set to one minimal conflict, in O(k log n) evaluations.

Junker’s QuickXplain: recursive halving that costs `O(k log(n/k))`
evaluations for a conflict of size `k` among `n` candidates, rather than
the `O(n)` of naive one-at-a-time removal.

* **Parameters:**
  * **evaluate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]) – The (cached) oracle.
  * **candidates** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Members that may be part of the conflict.
  * **background** ([`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)) – Members always present and assumed not, on their own, bad.
* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)
* **Returns:**
  A minimal subset `C` of `candidates` with `background | C` bad.

```pycon
>>> bad_pairs = [{'a', 'c'}]
>>> def ev(s):
...     ok = not any(p <= set(s) for p in bad_pairs)
...     return Evaluation(s, Verdict.PASS if ok else Verdict.FAIL)
>>> sorted(quickxplain(ev, ['a', 'b', 'c', 'd']))
['a', 'c']
```

### mergeset.solve.shrink_linear(evaluate, candidates, , background=frozenset({}))

One-at-a-time conflict shrinking: `n` evaluations, dead simple.

Kept because it is the obviously-correct reference that
[`quickxplain()`](#mergeset.solve.quickxplain) is checked against, and because for very small `n` it
is not actually slower.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)
