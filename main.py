import os
import json
import uuid
import requests
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from fastapi.responses import Response

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
    lead_id: str | None = None


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
        "You are a professional AI assistant for a digital agency.\n\n"
        "Conversation Flow Rules:\n"
        "1. First, politely ask for the visitor's full name.\n"
        "2. Then ask for their email address or phone number.\n"
        "3. Do NOT continue to service questions until both name and contact information are collected.\n"
        "4. Once collected, thank them briefly and continue with qualification questions.\n\n"
        "Qualification Goals:\n"
        "- Understand what service they are interested in.\n"
        "- Ask about their budget range (low, medium, high).\n"
        "- Ask about their timeline (urgent, soon, flexible).\n"
        "- Clarify their main goal or problem.\n\n"
        "Style Guidelines:\n"
        "- Keep responses concise and professional.\n"
        "- Ask one question at a time.\n"
        "- Do not overwhelm the visitor.\n"
        "- Be polite, confident, and helpful.\n\n"
        "Important:\n"
        "- Always guide the conversation step by step.\n"
        "- Ensure required information is collected before moving forward."
    )

    chat = [{"role": "system", "content": system_prompt}] + [
        {"role": m.role, "content": m.content} for m in messages
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=chat,
        temperature=0.4,
    )

    return response.choices[0].message.content

# ================= AI EXTRACTION =================

def extract_lead_data(messages):

    prompt = (
        "From the following conversation, extract structured lead information.\n\n"
    
        "IMPORTANT RULES:\n"
        "- Always infer intent. If the visitor is asking for a service, intent = sales.\n"
        "- If service like web development, website redesign, marketing, etc is mentioned, populate service_interest.\n"
        "- Convert numeric budgets into low/medium/high:\n"
        "  low = small personal project\n"
        "  medium = professional business budget\n"
        "  high = enterprise or large budget\n"
        "- Convert timeline phrases:\n"
        "  urgent = less than 2 weeks\n"
        "  soon = 2-6 weeks\n"
        "  flexible = more than 6 weeks\n"
        "- If information is missing, use 'unknown'.\n"
        "- Always preserve previously collected valid information.\n\n"
    
        "Return ONLY valid JSON with the following fields:\n"
        "- name\n"
        "- email\n"
        "- phone\n"
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


# ================= ROUTE =================
from fastapi.responses import Response

@app.get("/chatbot.js")
def serve_chatbot():
    js_code = """
(function () {
  const API_URL = "https://web-production-42726.up.railway.app/chat";
  const sessionId = crypto.randomUUID();
  let messages = JSON.parse(localStorage.getItem("chatMessages") || "[]");

  let leadId = localStorage.getItem("leadId");

  const bubble = document.createElement("div");
  bubble.innerHTML = `
    <div id="chat-container" style="
      position: fixed;
      bottom: 90px;
      right: 20px;
      width: 320px;
      height: 420px;
      background: white;
      border-radius: 10px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.2);
      display: none;
      flex-direction: column;
      overflow: hidden;
      font-family: Arial;
      z-index:999999;
    ">
      <div style="background:#111;color:white;padding:10px;">
        Chat with us
      </div>
      <div id="chat-messages" style="flex:1;padding:10px;overflow-y:auto;font-size:14px;"></div>
      <input id="chat-input" placeholder="Type a message..." 
        style="border:none;border-top:1px solid #ddd;padding:10px;width:100%;outline:none;" />
    </div>

    <button id="chat-toggle" style="
      position: fixed;
      bottom: 20px;
      right: 20px;
      background:#111;
      color:white;
      border:none;
      padding:15px;
      border-radius:50%;
      cursor:pointer;
      font-size:18px;
      z-index:999999;">
      💬
    </button>
  `;

  document.body.appendChild(bubble);

  const container = document.getElementById("chat-container");
  const toggle = document.getElementById("chat-toggle");
  const input = document.getElementById("chat-input");
  const messagesDiv = document.getElementById("chat-messages");

  toggle.onclick = () => {
    container.style.display =
      container.style.display === "flex" ? "none" : "flex";
  };

  input.addEventListener("keypress", async (e) => {
    if (e.key === "Enter" && input.value.trim() !== "") {
      const text = input.value;
      input.value = "";

      messages.push({ role: "user", content: text });
      localStorage.setItem("chatMessages", JSON.stringify(messages));

      messagesDiv.innerHTML += `<div><strong>You:</strong> ${text}</div>`;
      console.log("Sending to backend:", messages);
      const response = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          messages: messages,
          lead_id: leadId
        })
      });

      const data = await response.json();

      // ✅ Store leadId persistently
      leadId = data.lead_id;
      if (leadId) {
        localStorage.setItem("leadId", leadId);
      }
    
    messages.push({ role: "assistant", content: data.reply });
    localStorage.setItem("chatMessages", JSON.stringify(messages));

    messagesDiv.innerHTML += `<div><strong>AI:</strong> ${data.reply}</div>`;


      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
  });
})();
"""
    return Response(
        content=js_code,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"
        }
    )


@app.post("/chat")
def chat(request: ChatRequest):

    # 1️⃣ Generate AI reply
    print("Total messages received:", len(request.messages))
    print("Last message:", request.messages[-1].content)

    ai_reply = generate_ai_reply(request.messages)

    # 2️⃣ Append assistant reply to conversation
    updated_messages = request.messages + [
        Message(role="assistant", content=ai_reply)
    ]

    # 3️⃣ Extract structured data
    # 3️⃣ Extract structured data
    extracted = extract_lead_data(updated_messages)
    
    # Ensure extracted is always a dict
    if isinstance(extracted, list):
        extracted = extracted[0] if extracted else {}
    
    if not isinstance(extracted, dict):
        extracted = {}
    
    # 4️⃣ Deterministic contact detection (NOT AI dependent)
    latest_user_message = request.messages[-1].content.strip()
    
    is_phone = latest_user_message.isdigit() and len(latest_user_message) >= 7
    is_email = "@" in latest_user_message and "." in latest_user_message
    
    # 5️⃣ Lifecycle control
    lead_id = request.lead_id
    action = None
    
    if not lead_id:
        # First save only when contact detected
        if is_phone or is_email:
            lead_id = str(uuid.uuid4())
            action = "saveLead"
    else:
        # After first save, always update
        action = "updateLead"


    
    # 6️⃣ Send to Google Sheets only if action determined
    if action:
        payload = {
            "created_at": datetime.utcnow().isoformat(),
            "lead_id": lead_id,
            "source": "website-chatbot",
            **extracted,
            "conversation_log": [m.dict() for m in updated_messages],
        }

        try:
            requests.post(
                f"{API_URL}?action={action}",
                json=payload,
                timeout=10
            )
        except Exception:
            pass

    # 7️⃣ Return response + lead_id (if created)
    return {
        "reply": ai_reply,
        "lead_id": lead_id
    }


@app.get("/")
def health():
    return {"status": "Chatbot API running"}
