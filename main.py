import os
import json
import uuid
import requests
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# ================= CONFIG =================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_URL = os.getenv("GOOGLE_SCRIPT_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

# Allow WordPress domain (change later to specific domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= MODELS =================

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    session_id: str
    messages: list[Message]


# ================= JSON UTILS =================

def extract_json_from_text(text: str) -> dict:
    if not text:
        raise ValueError("Empty AI response")

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1:
            return json.loads(cleaned[start:end + 1])

    raise ValueError("Could not extract valid JSON")


# ================= AI CHAT =================

def generate_ai_reply(messages):

    system_prompt = (
        "You are a friendly AI assistant for a digital agency. "
        "Ask concise follow-up questions to understand the visitor’s needs, "
        "timeline, and budget. Keep responses professional and conversational."
    )

    chat = [{"role": "system", "content": system_prompt}] + [
        {"role": m.role, "content": m.content} for m in messages
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=chat,
        temperature=0.4
    )

    return response.choices[0].message.content


# ================= AI EXTRACTION =================

def extract_lead_data(messages):

    prompt = (
        "From the following conversation, extract structured lead information.\n\n"
        "Return ONLY valid JSON with the following fields:\n"
        "- intent (sales/support/other)\n"
        "- service_interest\n"
        "- budget_range (low/medium/high/unknown)\n"
        "- timeline (urgent/soon/flexible/unknown)\n"
        "- urgency_level (low/medium/high)\n"
        "- lead_score (0-100)\n"
        "- lead_temperature (hot/warm/cold)\n"
        "- ai_summary (1-2 sentences)\n"
        "- suggested_action\n\n"
        f"{json.dumps([m.dict() for m in messages], indent=2)}"
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0
    )

    try:
        return extract_json_from_text(response.choices[0].message.content)
    except Exception:
        return {
            "intent": "sales",
            "service_interest": "Website redesign",
            "budget_range": "unknown",
            "timeline": "unknown",
            "urgency_level": "medium",
            "lead_score": 50,
            "lead_temperature": "warm",
            "ai_summary": "Lead captured but details incomplete.",
            "suggested_action": "Review manually"
        }


# ================= AUTO SAVE =================

def auto_save_lead(messages):

    extracted = extract_lead_data(messages)

    if (
        extracted["intent"] == "sales"
        and extracted["service_interest"]
        and extracted["lead_score"] >= 60
        and (
            extracted["budget_range"] != "unknown"
            or extracted["timeline"] != "unknown"
        )
    ):

        payload = {
            "created_at": datetime.utcnow().isoformat(),
            "lead_id": str(uuid.uuid4()),
            "source": "website-chatbot",
            **extracted,
            "conversation_log": [m.dict() for m in messages],
        }

        try:
            requests.post(
                f"{API_URL}?action=saveLead",
                json=payload,
                timeout=10
            )
        except Exception:
            pass


# ================= ROUTE =================

@app.post("/chat")
def chat(request: ChatRequest):

    ai_reply = generate_ai_reply(request.messages)

    updated_messages = request.messages + [
        Message(role="assistant", content=ai_reply)
    ]

    auto_save_lead(updated_messages)

    return {"reply": ai_reply}


@app.get("/")
def health():
    return {"status": "Chatbot API running"}
