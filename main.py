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
1. VAGUE QUERIES: If the user's first request is extremely vague (e.g., "I need a test"), ask a clarifying question in "reply" and leave "recommendations" empty [].
2. SPECIFIC QUERIES: If the user mentions a specific role (like "Java developer") OR if you are responding to a follow-up message (like providing years of experience), you MUST provide 1 to 10 relevant recommendations. 
3. FALLBACK: If an exact skill match (like "Java") isn't in the catalog, recommend general software engineering, cognitive, or personality tests.
4. EXACT MATCHING: You MUST copy the "name" and "url" EXACTLY as they appear in the CATALOG. Do not change capitalization, add spaces, or alter the URL in any way.
5. SCHEMA: You MUST ALWAYS respond with a raw JSON object matching this exact schema:
{{
  "reply": "Your conversational response or clarifying question",
  "recommendations": [
    {{
      "name": "Exact Name from Catalog",
      "url": "Exact URL from Catalog",
      "test_type": "A single Test Type Code letter (e.g., K, P, A)"
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

@app.get("/")
def root():
    return {"status": "ok", "message": "SHL Assessment Recommender is running"}

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

    try:
        # Initialize the model with the system instructions
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=SYSTEM_PROMPT
        )
        
        
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
            
    except Exception as e:
        # Log exact errors to the server console for debugging
        print(f"\n--- GEMINI API ERROR ---\n{str(e)}\n------------------------\n")
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}")

    
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