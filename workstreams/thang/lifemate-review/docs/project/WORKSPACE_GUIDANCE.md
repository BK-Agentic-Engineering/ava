# Benchmark data quality and engineering constraints

User instruction: benchmark validity takes priority over computational convenience.

- Do not arbitrarily cap, downsample, or discard valid evaluation data to reduce runtime, storage, or implementation complexity.
- Select datasets for ground-truth reliability, distributional diversity, realistic conditions, subgroup coverage, and relevance.
- Keep representative evaluation and challenging/failure-oriented evaluation separate; define selection and reporting protocols explicitly.
- Prevent leakage, identify duplicates, validate labels, and preserve valid difficult or rare samples. Do not silently delete duplicates: distinguish accidental repeated records from legitimate repeated speech and report treatment.
- Determine sufficiency from coverage, subgroup sizes, uncertainty, and stability, not arbitrary sample-count targets.
- Use identical reproducible protocols across competing models; report aggregate/subgroup results and uncertainty where appropriate.
- Preserve essential source metadata, dataset versions, and evaluation configurations.
- Avoid unnecessary infrastructure, redundant artifacts, excessive abstraction, and automatic hash generation. Use hashes/checksums only for a concrete integrity or reproducibility benefit.
- Prefer the simplest implementation that satisfies scientific validity and reproducibility.

Never trade away benchmark validity for engineering convenience. Never introduce engineering complexity without a demonstrable benefit to evaluation quality or reliability.

Operational implications:
- Smoke/debug samples are for engineering validation only, never substitutes for full evaluation or evidence of dataset sufficiency.
- Default to full valid official evaluation splits. Resource constraints change execution scheduling, caching, and resumability, not scientific scope. If coverage is incomplete, report it as incomplete rather than claiming a full benchmark.
- Any designed sampling needs a scientific rationale and explicit coverage/uncertainty analysis; cost alone is not a sufficient rationale.
- A failure-driven diagnostic set must not be pooled into representative headline metrics.
- Source revision + frozen configuration is the default provenance. Content hashes are justified for duplicate/integrity checks or stale-cache prevention only where actually needed.

# Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.