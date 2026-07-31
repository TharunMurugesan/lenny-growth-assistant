# Agent Transcripts

Required by §7 of `lenny_growth_assistant_spec.md`: a log of the prompts used with Claude and coding
agents while building The Lenny Growth Assistant, **including failures and corrections**.

This folder is a working record, not a highlight reel. Where a first approach was wrong, the wrong
approach is written down alongside why it was replaced. A log that only contains decisions that
happened to be right is not evidence of engineering judgement.

## Files

| File | Contents |
| :--- | :------- |
| `01-phase-1-foundation.md` | Initial system prompt, spec interpretation, ambiguities found in the spec, and the design decisions reversed while writing the documentation. |
| `02-phase-2-backend.md` | Database schema, SQLAlchemy models, FastAPI application, session and chat routes. Four corrections, all caught by running the code. |
| `03-phase-3-agent-rag.md` | Ingestion, intent router, skills, SSE streaming. *(added when Phase 3 runs)* |
| `04-phase-4-frontend.md` | React UI, LLM toggle, Artifact Viewer. *(added when Phase 4 runs)* |

## Format

Each phase log uses the same structure:

1. **Prompt** — the instruction given, verbatim or summarized where long.
2. **Interpretation** — how the instruction was read, and what had to be inferred.
3. **Ambiguities and resolutions** — where the specification was silent or self-conflicting, and the
   position taken.
4. **Failures and corrections** — approaches attempted and abandoned, with the reason.
5. **Verification** — for phases that produce running code, what was actually executed and what it
   returned. Absent from Phase 1, which produced only documents.
6. **Output** — files produced.
7. **Open items** — anything deferred to a later phase.

## Conventions

- Decisions that materially shape the system are also recorded as ADRs in `architecture.md` §16.
  This folder records the *process*; the ADRs record the *conclusion*.
- Additions beyond the specification are flagged as additions wherever they appear, so a reviewer
  can always tell what was required from what was judged.
- No secrets, keys, or credentials appear in any transcript.
