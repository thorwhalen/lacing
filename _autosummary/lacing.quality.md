# lacing.quality

Inter-annotator agreement and boundary metrics.

Phase 0 ships four metrics from ANN-DOC §D, all as pure functions:

- [`cohen_kappa()`](#lacing.quality.cohen_kappa) — agreement between two annotators on a categorical label.
- [`krippendorff_alpha()`](#lacing.quality.krippendorff_alpha) — agreement across any number of annotators
  (handles missing data, multiple distance metrics).
- [`interval_iou()`](#lacing.quality.interval_iou) — Intersection-over-Union for two time intervals.
- [`boundary_iou()`](#lacing.quality.boundary_iou) — Average IoU between two sets of intervals (greedy match).

The doc cites Krippendorff thresholds: α > 0.8 reliable, 0.67–0.8 tentative,
< 0.67 discard. Kappa traditionally: >0.8 almost perfect, 0.6–0.8 substantial,
0.4–0.6 moderate.

Pure functions — no numpy dependency in Phase 0.

### Functions

| [`boundary_iou`](#lacing.quality.boundary_iou)(a, b)                              | Mean IoU between two sets of intervals via greedy best-match.   |
|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`cohen_kappa`](#lacing.quality.cohen_kappa)(a, b)                               | Cohen's kappa for two annotators on a categorical label.        |
| [`interval_iou`](#lacing.quality.interval_iou)(a, b)                              | Intersection-over-Union for two time intervals.                 |
| [`krippendorff_alpha`](#lacing.quality.krippendorff_alpha)(annotations, \*[, distance]) | Krippendorff's α across any number of annotators.               |

### lacing.quality.boundary_iou(a, b)

Mean IoU between two sets of intervals via greedy best-match.

For each interval in `a`, finds its highest-IoU match in `b` (without
replacement — once a `b` interval is matched it’s removed from the pool).
Unmatched intervals in either set contribute 0.0 to the mean.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  Mean IoU ∈ [0, 1]. Returns 0.0 if both sets are empty (defensible
  as a “no agreement to measure” baseline).

### lacing.quality.cohen_kappa(a, b)

Cohen’s kappa for two annotators on a categorical label.

* **Parameters:**
  * **a** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))]) – Annotator A’s labels.
  * **b** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))]) – Annotator B’s labels (must be the same length).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  κ ∈ [-1, 1]. 1 = perfect agreement, 0 = chance, negative = worse than chance.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If sequences differ in length or are empty.

Edge cases:
: If only one category appears across both annotators, both observed
  and expected agreement are 1.0; we return 1.0 by convention.

### lacing.quality.interval_iou(a, b)

Intersection-over-Union for two time intervals.

Returns 1.0 if both are equal point intervals at the same instant; 0.0
if they don’t intersect (including when only one is a point).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### lacing.quality.krippendorff_alpha(annotations, \*, distance=<function \_nominal_distance>)

Krippendorff’s α across any number of annotators.

* **Parameters:**
  * **annotations** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))]]]) – A list of annotators, each a sequence of labels (one per
    unit). Use `None` for a missing annotation by that annotator on
    that unit.
  * **distance** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable)), [`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Function `(x, y) -> float` measuring disagreement between
    two label values. Default is the nominal (0/1) distance.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  α. 1.0 = perfect agreement, 0.0 = chance.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If sequences differ in length, fewer than 2 annotators
      given, or fewer than 2 paired observations exist.
