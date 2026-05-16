from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json, os, re
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold


app = FastAPI(title="SHL Assessment Recommender", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load the catalog
CATALOG_PATH = Path(__file__).parent / "shl_catalog.json"
with open(CATALOG_PATH) as f:
    CATALOG: list[dict] = json.load(f)

def _fmt_catalog() -> str:
    lines = []
    for item in CATALOG:
        types = ", ".join(item.get("test_type_labels", item.get("test_types", [])))
        remote = "Remote:Yes" if item.get("remote_testing") else "Remote:No"
        adaptive = "Adaptive:Yes" if item.get("adaptive_irt") else "Adaptive:No"
        lines.append(f'- "{item["name"]}" | {remote} | {adaptive} | Types: [{types}] | URL: {item["url"]}')
    return "\n".join(lines)

CATALOG_TEXT = _fmt_catalog()
VALID_URLS = {item["url"] for item in CATALOG}


genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

SYSTEM_PROMPT = f"""
You are an expert SHL Assessment Recommender API.
Your job is to recommend appropriate assessment tests from the catalog below based on the user's hiring needs.

CATALOG:
{CATALOG_TEXT}

RULES:
1. VAGUE QUERIES: If the user's first request is extremely vague (e.g., "I need a test" with no role or skill), ask ONE clarifying question in "reply" and leave "recommendations" as [].

2. SPECIFIC QUERIES — MANDATORY RECOMMENDATIONS: If the user mentions ANY of the following, you MUST output between 1 and 10 recommendations. No exceptions:
   - A job role (e.g., "Java developer", "sales manager", "data scientist", "software engineer")
   - A skill or technology (e.g., "Python", "SQL", "Java")
   - A seniority level (e.g., "mid-level", "senior", "4 years experience")
   - A follow-up message that provides more context after a clarifying question
   This rule overrides all other rules. Even if the match is imperfect, you MUST recommend.

3. FALLBACK — ALWAYS RECOMMEND SOMETHING: If an exact skill match is not in the catalog, you MUST still recommend the closest alternatives:
   - General cognitive ability tests
   - Personality & Behavior tests (type P)
   - General software/technology tests
   - Never return empty recommendations when a role or skill has been mentioned.

4. EXACT MATCHING: Copy "name" and "url" character-for-character from the CATALOG above. Do not paraphrase, abbreviate, or alter URLs.

5. OUT OF SCOPE: If the user asks something completely unrelated to hiring or assessments (e.g., salary advice, weather), set recommendations to [] and politely decline in "reply".

6. SCHEMA: You MUST ALWAYS respond with ONLY a raw JSON object — no markdown, no explanation, no extra text:
{{
  "reply": "Your conversational response",
  "recommendations": [
    {{
      "name": "Exact Name from Catalog",
      "url": "Exact URL from Catalog",
      "test_type": "A single Test Type Code letter (e.g., K, P, A, B, C, D, E, S)"
    }}
  ],
  "end_of_conversation": false
}}
"""

class Message(BaseModel):
    role: str  
    content: str

class ChatRequest(BaseModel):
    messages: list[Message]

class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str

class ChatResponse(BaseModel):
    reply: str
    recommendations: list[Recommendation]
    end_of_conversation: bool


def parse_response(raw: str) -> dict:
    # Strip markdown fences if present
    text = raw.strip()
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find json object within the text
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {
        "reply": "I encountered an issue processing your request. Could you rephrase?",
        "recommendations": [],
        "end_of_conversation": False,
    }

def validate_recommendations(recs: list) -> list[dict]:
    """Ensure every URL in recommendations exists in our catalog."""
    valid = []
    for r in recs:
        if isinstance(r, dict) and r.get("url") in VALID_URLS:
            valid.append(r)
    return valid


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    
    gemini_messages = []
    for m in request.messages:
        if m.role not in ("user", "assistant"):
            raise HTTPException(status_code=400, detail=f"Invalid role: {m.role}")
        
        role = "model" if m.role == "assistant" else "user"
        gemini_messages.append({
            "role": role, 
            "parts": [m.content]
        })
   
    if len(gemini_messages) > 8:
        gemini_messages = gemini_messages[-8:]

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT
    )

    raw = None
    last_error = None
    for attempt in range(3):  # Retry up to 3 times on rate limit errors
        try:
            import time as _time
            if attempt > 0:
                _time.sleep(3 * attempt)  # 3s, then 6s back-off

            response = model.generate_content(
                gemini_messages,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=1000,
                ),
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                }
            )

            if response.prompt_feedback and response.prompt_feedback.block_reason:
                raw = '{"reply": "Request blocked by safety filters.", "recommendations": [], "end_of_conversation": false}'
            else:
                raw = response.text
            break  # Success — exit retry loop

        except Exception as e:
            last_error = e
            print(f"\n--- GEMINI API ERROR (attempt {attempt+1}) ---\n{str(e)}\n")
            if "quota" in str(e).lower() or "429" in str(e) or "rate" in str(e).lower():
                continue  # Retry on rate limit
            break  # Don't retry on other errors

    if raw is None:
        raise HTTPException(status_code=502, detail=f"LLM API error: {last_error}")

    
    data = parse_response(raw)

    
    raw_recs = data.get("recommendations", [])
    clean_recs = validate_recommendations(raw_recs)

    return ChatResponse(
        reply=data.get("reply", ""),
        recommendations=[Recommendation(**r) for r in clean_recs],
        end_of_conversation=bool(data.get("end_of_conversation", False)),
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)