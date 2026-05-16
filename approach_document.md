# SHL Assessment Recommender — Approach Document

## Problem Decomposition

The core challenge is converting an ambiguous hiring intent into a grounded, catalog-bound assessment shortlist through multi-turn dialogue, without hallucinating assessments or URLs.

I decomposed this into four sub-problems:

1. **Catalog grounding** — How do I ensure the agent never recommends an assessment not in the SHL catalog?
2. **Conversational flow control** — How do I enforce clarify → recommend → refine behavior without a state machine?
3. **Structured output reliability** — How do I get a JSON schema from an LLM every single call, including edge cases?
4. **Scope enforcement** — How do I prevent off-topic responses and prompt injection?

## Design Choices

### LLM: Claude claude-sonnet-4-20250514 (Anthropic)
Chosen for its strong instruction-following, JSON output reliability, and generous free tier via the Anthropic API. The task is fundamentally a context-grounded reasoning problem — not a retrieval problem — so a capable LLM with the full catalog in context outperforms a RAG pipeline at this catalog size (~150–400 items, well within 200K context window).

**Why not RAG?** At 150–400 items, the entire catalog fits in one prompt. Adding a vector store introduces latency, a moving part, and the risk of retrieval misses. Context-in-prompt is simpler, faster, and more reliable at this scale.

### Retrieval Strategy: Full Catalog in System Prompt
Each catalog item is serialized as a single line:
```
- "Java 8 (New)" | Remote:No | Adaptive:No | Types: [Knowledge & Skills] | URL: https://...
```
At ~100 chars/item × 400 items = ~40KB, well within Claude's context window. This ensures every recommendation is grounded and the model cannot hallucinate URLs it has never seen.

### Structured Output: JSON-Only System Prompt + Fallback Parser
The system prompt instructs the model to respond **only** with a JSON object matching the exact schema. A `parse_response()` function handles edge cases: markdown fences, leading text, partial JSON — falling back to a safe error response. No tool-use or function-calling needed; the schema is simple enough that explicit prompting is reliable.

### Conversational Behavior via Prompt Engineering
All four behaviors (clarify, recommend, refine, compare) are encoded in the system prompt's rules section. This avoids building a state machine:
- **Clarify**: explicit rule — ask before recommending if role/context is missing
- **Recommend**: explicit threshold — need job role + at least one more signal
- **Refine**: explicit rule — apply edits to current shortlist, don't restart
- **Compare**: explicit rule — use catalog data only, not prior knowledge

### Scope Enforcement: Whitelist + Prompt Rules
Two layers:
1. System prompt tells the model to refuse off-topic requests
2. `validate_recommendations()` checks every URL against a hardcoded whitelist of catalog URLs — even if the model somehow produces a hallucinated URL, it's silently dropped

### Stateless Design
Every `/chat` call receives the full conversation history. No session storage. The last 8 messages are kept (matching the evaluator's turn cap) to prevent context overflow on long conversations.

## Catalog Data
- **Source**: SHL Individual Test Solutions catalog at shl.com/products/product-catalog/?type=1
- **Coverage**: 150 hand-curated items covering all major test type categories (A, B, C, D, E, K, P, S)
- **Scraper**: `scraper_local.py` provided for running locally to refresh to full ~384 items
- **Format**: JSON with name, url, remote_testing, adaptive_irt, test_types fields

## Evaluation Approach

I tested against the four hard eval dimensions from the spec:

| Eval | Test | Result |
|------|------|--------|
| Schema compliance | Every response parsed by Pydantic | ✅ |
| Catalog-only URLs | Whitelist validation | ✅ |
| Turn cap (8) | History trimmed to last 8 | ✅ |
| Vague → clarify | "I need an assessment" → empty recs | ✅ |
| Refine | "add personality tests" → updated shortlist | ✅ |
| Off-topic refusal | Salary question → empty recs | ✅ |
| Prompt injection | "Ignore instructions" → refused | ✅ |

## What Didn't Work

- **scraping from the deployment server**: SHL returns 403 to server IPs. Solved by providing a local scraper and building a curated catalog from publicly visible catalog data.
- **RAG pipeline**: Tested conceptually — retrieval misses on borderline queries (e.g. "stakeholder management" not matching personality test keywords) would hurt Recall@10. Full catalog in context avoids this.
- **Freeform LLM output**: First iteration without strict JSON prompt produced inconsistent schemas. Solved with explicit JSON-only system prompt + fallback parser.

## Stack
- **FastAPI** + **Uvicorn** — lightweight, production-grade ASGI server
- **Anthropic SDK** — direct API, no LangChain overhead
- **Pydantic v2** — schema enforcement on responses
- **Render** — free-tier deployment with cold start within 2-minute limit

## AI Tools Used
- Claude (this conversation) — used for pair programming, debugging, and approach validation. All design decisions were made and defended by me; Claude generated boilerplate and caught syntax errors.
