# SHL Assessment Recommender

Conversational agent that recommends SHL Individual Test Solutions based on hiring context.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your Gemini API key
export GEMINI_API_KEY="your_api_key_here"
export PORT=8000

# 3. (Optional) Refresh the catalog from SHL's live site
python scraper_local.py
cp shl_catalog_full.json shl_catalog.json

# 4. Run the server
uvicorn main:app --host 0.0.0.0 --port 8000

# 5. Test
python test_api.py
```

## API

### GET /health
```json
{"status": "ok"}
```

### POST /chat
```json
{
  "messages": [
    {"role": "user", "content": "Hiring a Java developer who works with stakeholders"},
    {"role": "assistant", "content": "Sure. What is seniority level?"},
    {"role": "user", "content": "Mid-level, around 4 years"}
  ]
}
```

Response:
```json
{
  "reply": "Here are 5 assessments that fit a mid-level Java dev...",
  "recommendations": [
    {"name": "Java 8 (New)", "url": "https://www.shl.com/...", "test_type": "K"},
    {"name": "OPQ32r", "url": "https://www.shl.com/...", "test_type": "P"}
  ],
  "end_of_conversation": false
}
```

## Deploy to Render (Free)

1. Push this repo to GitHub
2. Create new Web Service on render.com → connect your repo
3. Set env var: `GEMINI_API_KEY`
4. Deploy

## Architecture

- **FastAPI** - stateless REST API
- **Claude claude-sonnet-4-20250514** - reasoning engine (via Anthropic API)
- **shl_catalog.json** - 150+ SHL Individual Test Solutions (scraped + curated)
- **Context engineering** - full catalog embedded in system prompt; structured JSON output enforced
- **Validation layer** - all recommendation URLs validated against catalog whitelist

## Scoring Strategy

- ✅ Schema compliance - strict JSON schema enforced, pydantic validation
- ✅ Catalog-only URLs - whitelist validation on every response
- ✅ Turn cap (8) - history trimmed to last 8 messages
- ✅ Clarify before recommend - system prompt enforces min context
- ✅ Refine - system prompt handles mid-conversation edits
- ✅ Compare - grounded answers from catalog data
- ✅ Out-of-scope refusal - explicit rules in system prompt
