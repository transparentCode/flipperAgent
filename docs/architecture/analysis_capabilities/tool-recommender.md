# Tool recommender boundary

The deterministic analysis-capability kernels are the analytical authority. A
future tool recommender may suggest or rank available tools, but it cannot
change kernel results, provenance, causal cutoffs, or publication semantics.
World-model and strategy agents may accept, reject, or ignore a suggestion.
`libs.selection` is not the home of the recommender.

R4A adds no recommender, training data, labels, utility formula, model, bandit,
RL policy, PnL objective, or future-return target. The taxonomy in
`tool-taxonomy.yaml` describes the vocabulary; it is not a callable plugin
registry and does not activate planned or deferred tools.

The deferred research sequence is:

```text
R5A  full-information historical tool-evidence dataset
R5B  deterministic heuristic/ranking baseline
R5C  supervised ML challenger after an explicit dependency decision
R6   contextual-bandit shadow challenger
R7   sequential RL only if multi-step tool planning demonstrates a real need
```

The first recommender question is descriptive tool usefulness, not buy/sell
prediction. Any future ranking contract requires a separate design and
approval; it must leave the deterministic kernels authoritative.
