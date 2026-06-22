# ADR 004: The Reasoning Bank

## Decision
Reasoning strings for the final CSV export are pre-computed and stored in a static "Reasoning Bank" (Phase 10), rather than generated dynamically online.

## Context
The online pipeline must run on a CPU within 5 minutes, with no API access. We are required to output a `reasoning` string for the top 100 candidates.

## Alternatives Considered
- **Local LLM**: Run a 7B model locally during the online phase.
- **Template String**: Use basic Python `f-strings` to generate reasoning.

## Why Rejected
- **Local LLM**: Too slow. A 7B model on CPU takes 20-30 seconds per candidate. 100 candidates = 30+ minutes (violating the 5-min constraint).
- **Template String**: Too robotic, fails to impress the judges.

## Consequences
We spend offline GPU compute to generate beautiful, nuanced LLM reasoning for the entire Top 500 candidate pool, save it to a `.parquet` dictionary, and the online script simply performs an `O(1)` dictionary lookup.
