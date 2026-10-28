# Restore report: runbook-rehearsal

- Method: replay of `search_replace` editFileResult unified diffs in order; shell-created extras filled from transcript commands
- NVIDIA / OpenRouter generation: **not needed** (full tree reconstructable; all tests green)
- Restored from transcript diffs: 58 paths via search_replace
- Filled from transcript shell (not in diffs):
  - `src/rehearse/data/runbook.schema.json` (cp from `schema/runbook.schema.json`)
  - `src/rehearse/py.typed` (empty marker; listed in final find + package-data)
  - `tests/__init__.py` (empty; present in original git commit)
- Tests: `pytest` → **32 passed** (matches transcript final 32)
- Ready to push: **yes**
- Gaps: none functional. Original cloud agent authored as Cursor; local commit uses Wasaf Abbasi identity per brief.
