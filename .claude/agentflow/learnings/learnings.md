
## 2026-02-23: A2/A3 Code Review Learnings

- Codex-generated code tends to skip ID format prefixes specified in specs (e.g., missing `backup_` prefix). Always verify generated IDs against spec format literally.
- Codex may add "conservative" policies not in the spec (e.g., never deleting `active` backups in cleanup). These need explicit documentation or removal.
- When a module reads the same file N times in a loop (e.g., `get_trend` calling `_iter_events` 30 times), flag it as a performance issue early -- it's a common pattern in generated code.

## 2026-02-23: A6/A7 Code Review -- Codex Return Schema Drift
- Codex-generated code tends to diverge from spec return schemas silently.
- A6 `compact()` used `compacted_history` instead of `compressed_history`, and flattened the `stats` sub-dict.
- A7 `lightweight_observe()` returned an internal log dict instead of the spec-required `{patterns_noticed, suggestions, urgency}`.
- Lesson: Always include schema-assertion tests that directly validate return dict keys against spec.
