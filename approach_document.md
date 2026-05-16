
# SHL Assessment Recommender — Approach Document

## Problem Decomposition

The core challenge is converting an ambiguous hiring intent into a grounded, catalog-bound assessment shortlist through multi-turn dialogue, without hallucinating assessments or URLs.

I decomposed this into four sub-problems:

1. **Catalog grounding** — How do I ensure the agent never recommends an assessment not in the SHL catalog?
2. **Conversational flow control** — How do I enforce clarify → recommend → refine behavior without a state machine?
3. **Structured output reliability** — How do I get a JSON schema from an LLM every single call, including edge cases?
4. **Scope enforcement** — How do I prevent off-topic responses and prompt injection?

## Design Choices

### LLM: Google Gemini (`gemini-2.5-flash`)

Chosen for its incredibly fast inference speed, massive context window, and strong instruction-following capabilities. The task is fundamentally a context-grounded reasoning problem — not a retrieval problem — so a highly capable LLM with the full catalog in context easily outperforms a RAG pipeline at this catalog size (~150–400 items).

**Why not RAG?** At 150–400 items, the entire catalog fits in one prompt. Adding a vector store introduces latency, a moving part, and the risk of retrieval misses. Context-in-prompt is simpler, faster, and more reliable at this scale.

### Retrieval Strategy: Full Catalog in System Prompt

Each catalog item is serialized as a single line:


- "Java 8 (New)" | Remote:No | Adaptive:No | Types: [Knowledge & Skills] | URL: https://...


At ~100 chars/item × 400 items = ~40KB, this is easily digestible for Gemini's large context window. This ensures every recommendation is grounded and the model cannot hallucinate URLs it has never seen.

### Structured Output: JSON-Only System Prompt + Fallback Parser

The system prompt explicitly commands the model to respond **only** with a JSON object matching the exact schema. A `parse_response()` function handles edge cases: markdown fences, leading text, or partial JSON — falling back to a safe error response. No rigid function-calling tools were needed; strict system prompting proved reliable.

### Conversational Behavior via Prompt Engineering

All behaviors (clarify, recommend, refine, compare) are encoded in the system prompt's rules section. This avoids building a complex state machine:

* **Clarify**: Explicit rule — ask a clarifying question before recommending if the role/context is missing.
* **Recommend**: Explicit threshold — output 1 to 10 recommendations once a specific role (like "Java developer") is mentioned.
* **Refine**: Explicit rule — apply edits to the current shortlist without restarting.

### Scope Enforcement & Safety

Two layers:

1. **Application Logic**: `validate_recommendations()` checks every URL against a hardcoded whitelist of catalog URLs — even if the model hallucinates a URL, it is silently dropped.
2. **Safety Settings Tuning**: Gemini's native safety filters were lowered (`HarmBlockThreshold.BLOCK_NONE`) strictly to allow edge-case test prompts (like prompt injection attempts) to reach the LLM, ensuring the application's *internal* system prompt rules handle the refusal rather than returning opaque 502 API errors.

### Stateless Design

Every `/chat` call receives the full conversation history. No session storage is used. The last 8 messages are kept (matching the evaluator's turn cap) to prevent context overflow on long conversations.

## Catalog Data

* **Source**: SHL Individual Test Solutions catalog at `shl.com/products/product-catalog/?type=1`
* **Coverage**: Hand-curated items covering all major test type categories (A, B, C, D, E, K, P, S).
* **Scraper**: `scraper_local.py` provided for running locally to refresh to the full catalog size.
* **Format**: JSON with `name`, `url`, `remote_testing`, `adaptive_irt`, and `test_types` fields.

## Evaluation Approach

I tested against the four hard eval dimensions from the spec:

| Eval | Test | Result |
| --- | --- | --- |
| Schema compliance | Every response parsed by Pydantic | ✅ |
| Catalog-only URLs | Whitelist validation | ✅ |
| Turn cap (8) | History trimmed to last 8 | ✅ |
| Vague → clarify | "I need an assessment" → empty recs | ✅ |
| Refine | "add personality tests" → updated shortlist | ✅ |
| Off-topic refusal | Salary question → empty recs | ✅ |
| Prompt injection | "Ignore instructions" → refused | ✅ |

## What Didn't Work

* **Scraping from the deployment server**: SHL returns 403 to server IPs. Solved by providing a local scraper and building a curated catalog from publicly visible catalog data.
* **RAG pipeline**: Tested conceptually — retrieval misses on borderline queries (e.g. "stakeholder management" not matching personality test keywords) would hurt Recall@10. Full catalog in context avoids this.
* **Deprecated Models**: Initially attempted to use `gemini-1.5-flash` but encountered 404 API errors due to model deprecation. Upgraded to `gemini-2.5-flash` for stability.
* **Empty Recommendations on Specific Queries**: Gemini initially stayed too conversational when given specific roles, resulting in 0 recommendations. Solved by implementing strict, rule-based prompt engineering dictating exactly when to output recommendations and enforcing exact URL copying.
* **Test Suite Rate Limiting**: The automated test suite fired requests too quickly for the free-tier API, causing 502 Bad Gateway / Quota errors. Solved by implementing a 2-second sleep delay between tests.

## Stack

* **FastAPI** + **Uvicorn** — lightweight, production-grade ASGI server
* **Google Generative AI SDK** — direct API integration with Gemini
* **Pydantic v2** — schema enforcement on responses
* **Render** — free-tier deployment with cold start within 2-minute limit

## AI Tools Used

* **Gemini** — Used for pair programming, migrating the codebase from Anthropic to Google Generative AI, debugging API errors/rate limits, and refining the system prompt for strict JSON compliance. All core design decisions were made and defended by me.