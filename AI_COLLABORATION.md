# AI_COLLABORATION.md

**Project:** Autonomous Regional Trailer Director (prototype)
**Purpose:** Document how AI tools are used to build this prototype, and how their output is verified rather than blindly accepted.
**Status:** Plan of collaboration. The **Usage log** (§6) must be filled in with what actually happened during the build. Do not backfill it with claims that did not occur.

---

## 1. Tool roles (as defined in SUMMARY.md §6)

| Tool | Used for | Not used for |
|---|---|---|
| **Claude Opus 4.6** | Architecture design; validator design and edge cases; hard reasoning about routing/repair/impact logic; code review; debugging assistance; documentation drafting and review | Final authority on correctness; producing test outcomes; runtime decisions about rights/policy (runtime hard checks are deterministic code) |
| **Gemini (Pro / multimodal)** | Synthetic fixture generation (scenes, dialogue, placeholder dialect text); structured extraction experiments; optional video/visual understanding experiments; optional live planner backend (behind `ModelClient`) | Rights, spoiler or policy decisions; anything treated as verified without checks; linguistic certification of dialect text |
| **Antigravity** | Repository creation; implementation; terminal execution; running tests; iterative debugging; file organization | Deciding architecture changes (those go through §4) |

Notes: model names are as specified in `SUMMARY.md`. Capabilities are not assumed beyond what is observed in use. If a tool behaves differently than planned, record it in the usage log.

## 2. Working method

1. **Docs first.** The documentation set (this folder) is the specification the coding agent works from. `SUMMARY.md` is the source of truth.
2. **Small, reviewable steps.** One module or validator per agent task, with the acceptance test named in the prompt (e.g. "implement `SpoilerValidator` so T3 passes; do not modify tests").
3. **Tests define done.** Tests come from `VALIDATION_AND_TESTING.md`; the agent may add tests but may not weaken or delete existing ones without a recorded reason.
4. **Human review of every diff.** Read the diff before accepting; run the tests locally; check that new code respects the LLM/deterministic boundary.
5. **Challenge generated content** (§3) before it enters the fixture or docs.
6. **Record decisions** that deviate from the spec (§4) and rejected AI suggestions (§5).

## 3. Verification process

| Artifact | How it is verified |
|---|---|
| Generated code | Code review against the architecture (nine nodes, validator independence, no LLM in hard checks); run full `pytest`; run the CLI in replay mode; check determinism (`diff` of two runs) |
| Validators | Each has unit tests covering pass, fail and boundary cases; mutation-style tests (change one fixture field, expect a specific error code); `test_hard_fail_never_downgraded`; `test_validator_exception_fails_closed` |
| Generated fixture (Gemini/Claude-assisted) | Manual review of scene bounds, reveal windows, flag windows and cue containment against DATA_SPEC §7.1; schema tests; check for accidental real names, real brands, or real policy language; confirm `synthetic: true` everywhere |
| Dialect placeholder text | Marked `native_review: PENDING`; never presented as linguistically verified |
| Replay recordings | Reviewed by hand; labeled as fixtures; `trailer_plans.traps` traps documented |
| LLM outputs at runtime | Pydantic schema validation; validators; advisory-only for concerns; logged with cost |
| Architecture claims | Each claim in README/ARCHITECTURE is tied to a test or a file; no aspirational statements |
| Documentation | Consistency pass (project name, node names, validator names, statuses, file names) |

Principles: **assume AI output can be wrong**; prefer deterministic checks for anything a rule can express; where a model disagrees with a validator, the validator wins and the disagreement is logged.

## 4. Deviations from the plan

Any deviation from `SUMMARY.md` or these docs is recorded here with reason and time/scope justification, e.g. "Dropped live Gemini client per cut list (IMPLEMENTATION_PLAN §11)". *(Empty until something changes.)*

| Date | Deviation | Reason | Approved by |
|---|---|---|---|
| | | | |

## 5. Rejected or modified AI suggestions

Keep a running list (this is evidence of critical use of AI tools). Template:

| Tool | Suggestion | Why rejected/modified | Outcome |
|---|---|---|---|
| | | | |

Categories worth noting: proposals to add infrastructure not in scope; validators that call an LLM for hard decisions; code that swallows exceptions as passes; tests that only assert logging; over-broad refactors.

## 6. Usage log (actual build record)

| Phase | Tool | What was asked | What was accepted/changed | Verification performed |
|---|---|---|---|---|
| Phase 0 | Claude / Antigravity | Project scaffold, LangGraph skeleton, test framework | Scaffolding, pytest runner, CLI parser | 41 smoke tests passed |
| Phase 1 | Antigravity | Pydantic v2 domain models, JSON schema exporter | Complete models in `src/models.py`, `export_schemas.py` | 86 schema and model tests passed |
| Phase 2 | Claude / Antigravity | Synthetic evaluation fixture ("The Missing Letter") | Complete 10-fixture synthetic package in `data/` | 174 fixture validation tests passed |
| Phase 3–5 | Antigravity | Evidence indexing, story analysis, constraint mapper, planners | `src/evidence.py`, `src/story.py`, `src/constraints.py`, `src/planners.py` | 21 planner and pipeline tests passed |
| Phase 6–7 | Antigravity | 9 deterministic validators, repair loop, graph routing | `src/validators/*`, `src/repair.py`, `src/graph.py` | Validator suites + repair termination tests passed |
| Phase 8 | Antigravity | ChangeImpactAnalyzer, reverse lookup, selective replanning | `src/impact.py`, scoped validation, byte hash snapshotting | 6 tests in `test_changed_contract.py` passed; 11 unaffected segments byte-identical |
| Phase 9 | Antigravity | HostileMockClient, adversarial tests, prompt injection | `HostileMockClient` in `src/llm.py`, `tests/test_adversarial.py` | 10 adversarial invariant tests passed |
| Phase 10 | Antigravity | Replay hardening, determinism audit, `sample_run/` generation | Lexicographic sorting in `planners.py`, live client fallback | Two-run byte-identical check passed (10/10 artifacts) |
| Phase 11 | Antigravity | README & documentation consistency pass | `README.md`, verified CLI commands, final audit | Full test suite: 393 passed, 0 failed |

## 7. Data and secrets handling

- No API keys committed; `.env.example` only. Replay mode needs no keys.
- Synthetic data only; no real STAGE material was provided or used.
- If any assistant transcript is attached to the submission, remove keys and personal data first.

## 8. Honest claims

This document does not claim that AI tools wrote correct code unaided, that generated data is realistic, or that any model's cultural or linguistic output is reliable. It claims only that AI tools were used as assistants inside a process where tests, deterministic validators, and human review decide what is accepted.
