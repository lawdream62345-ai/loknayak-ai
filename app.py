# ═══════════════════════════════════════════════════════════════════
#  ⚖️ VIDURA AI — CORPORATE ENTERPRISE EDITION
# ═══════════════════════════════════════════════════════════════════

import gradio as gr
import requests
import time
import os
import re
import json
import PyPDF2
import docx
import base64
import tempfile
from google import genai
from google.genai import types

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

import firebase_admin
from firebase_admin import credentials, firestore

APP_NAME = "VIDURA AI"
print("=" * 60)
print(f"  🚀 STARTING {APP_NAME} ENTERPRISE SERVER")
print("=" * 60)

GROQ_KEY = os.environ.get("GROQ_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

# ═══════════════════════════════════════════════════════════════════
# 1. FIRESTORE DATABASE INITIALIZATION
# ═══════════════════════════════════════════════════════════════════
db = None
firebase_json_env = os.environ.get("FIREBASE_CREDENTIALS_JSON")

if firebase_json_env:
    try:
        cred_dict = json.loads(firebase_json_env)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client(database_id="default")
        print("✅ Firestore Enterprise Cloud Database Connected Successfully!")
    except Exception as e:
        print("⚠️ Firestore Initialization Warning:", e)
else:
    print("ℹ️ FIREBASE_CREDENTIALS_JSON not found. Running in Local Memory mode.")

def sanitize_history(history_data):
    if not history_data: return []
    clean_history = []
    for item in history_data:
        if isinstance(item, dict):
            role = item.get("role", "assistant")
            if role in ["bot", "VIDURA AI", "VIDURA"]: role = "assistant"
            clean_history.append({"role": role, "content": str(item.get("content", ""))})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            if item[0]: clean_history.append({"role": "user", "content": str(item[0])})
            if item[1]: clean_history.append({"role": "assistant", "content": str(item[1])})
    return clean_history

def save_chat_to_cloud(email, title, history):
    if not db or not email or not title:
        return
    try:
        safe_doc_id = re.sub(r'[^a-zA-Z0-9 _-]', '', title).strip()[:80]
        if not safe_doc_id: safe_doc_id = "Untitled_Matter"
        
        doc_ref = db.collection("users").document(email).collection("chats").document(safe_doc_id)
        doc_ref.set({
            "title": title,
            "history": history,
            "updated_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
    except Exception as e:
        print(f"❌ Save Error: {e}")

def fetch_user_chats_from_cloud(email):
    if not db or not email: return {}
    try:
        chats_ref = db.collection("users").document(email).collection("chats")
        docs = chats_ref.stream()
        
        chat_data = []
        for doc in docs:
            data = doc.to_dict()
            title = data.get("title", doc.id)
            history = data.get("history", [])
            updated_at = data.get("updated_at")
            timestamp = updated_at.timestamp() if updated_at and hasattr(updated_at, 'timestamp') else 0
            chat_data.append({"title": title, "history": history, "timestamp": timestamp})
        
        chat_data.sort(key=lambda x: x["timestamp"], reverse=True)
        user_chats = {item["title"]: sanitize_history(item["history"]) for item in chat_data}
        return user_chats
    except Exception as e:
        print(f"❌ Fetch Error: {e}")
        return {}

# ═══════════════════════════════════════════════════════════════════
# 2. FASTAPI & OAUTH SETUP
# ═══════════════════════════════════════════════════════════════════
app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key="vidura-corporate-key-2026",
    same_site="lax",
    https_only=True,
    max_age=14 * 24 * 3600
)

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get('OAUTH_CLIENT_ID', ''),
    client_secret=os.environ.get('OAUTH_CLIENT_SECRET', ''),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

@app.api_route("/login", methods=["GET", "POST", "OPTIONS"])
async def login(request: Request):
    redirect_uri = request.url_for('auth')
    redirect_uri_str = str(redirect_uri).replace("http://", "https://")
    return await oauth.google.authorize_redirect(request, redirect_uri_str)

@app.api_route("/auth", methods=["GET", "POST", "OPTIONS"])
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user:
            request.session['user'] = dict(user)
    except Exception as e:
        print("Auth Exception:", e)
    return RedirectResponse(url='/', status_code=303)

@app.api_route("/logout", methods=["GET", "POST", "OPTIONS"])
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url='/', status_code=303)

# ═══════════════════════════════════════════════════════════════════
# 3. AI ENGINE, CUSTOM BASE64 WHISPER DICTATION & CHAT CONTROLLER
# ═══════════════════════════════════════════════════════════════════

def process_base64_audio(b64_string):
    """Decodes custom JS Base64 audio seamlessly passed from the browser memory."""
    if not b64_string or not GROQ_KEY:
        return ""
    try:
        if "," in b64_string:
            b64_string = b64_string.split(",")[1]
            
        audio_data = base64.b64decode(b64_string)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
            temp_audio.write(audio_data)
            temp_audio_path = temp_audio.name
            
        with open(temp_audio_path, "rb") as file:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                files={"file": file},
                data={"model": "whisper-large-v3-turbo"}
            )
            
        os.remove(temp_audio_path)
        data = response.json()
        return data.get("text", "").strip()
    except Exception as e:
        print(f"Base64 Transcription Error: {e}")
        return "⚠️ Voice dictation failed."

def parse_file(file_path):
    if not file_path: return ""
    try:
        ext = os.path.splitext(file_path)[1].lower()
        text = ""
        if ext == ".pdf":
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted: text += extracted + "\n"
        elif ext in [".docx", ".doc"]:
            doc = docx.Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs if p.text])
        return text.strip()
    except Exception as e:
        return f"[Document Parse Error]"

def call_llm(system_prompt, user_prompt, model_name="openai/gpt-oss-120b"):
    if GROQ_KEY:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={"model": model_name, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.2, "max_tokens": 1800},
                timeout=25
            )
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"], f"Groq ({model_name})"
        except Exception as e:
            print(f"LLM Call Error ({model_name}): {e}")

    if GEMINI_KEY:
        try:
            client = genai.Client(api_key=GEMINI_KEY)
            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=user_prompt,
                config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.2, max_output_tokens=2000)
            )
            return response.text, "Gemini Flash"
        except Exception: pass
    return None, "None"

def process_chat(user_message, file_path, pipeline_mode, history, chats_store, current_title, user_email):
    if not user_message.strip() and not file_path:
        yield "", file_path, gr.update(), history, chats_store, current_title, gr.update()
        return

    doc_text = parse_file(file_path) if file_path else ""
    if len(doc_text) > 20000: doc_text = doc_text[:20000]

    memory_context = ""
    if history:
        memory_context = "--- PREVIOUS MATTERS & CONTEXT ---\n"
        for msg in history:
            role_str = "COUNSEL/USER" if msg.get("role") == "user" else "VIDURA AI"
            memory_context += f"{role_str}: {msg.get('content', '')}\n\n"

    display_msg = user_message
    if file_path: display_msg = f"📄 **Attached Legal File:** `{os.path.basename(file_path)}`\n\n" + user_message

    history.append({"role": "user", "content": display_msg})
    
    active_title = current_title if (current_title and current_title != "New Matter") else (user_message[:32] + "..." if len(user_message) > 32 else "Document Review")
    
    chats_store[active_title] = list(history)
    if user_email: save_chat_to_cloud(user_email, active_title, list(history))

    input_payload = f"{memory_context}\n--- CURRENT LEGAL INQUIRY ---\n{user_message}\n"
    if doc_text: input_payload += f"\n--- ATTACHED DOCUMENT CONTEXT ---\n{doc_text}\n"

    history.append({"role": "assistant", "content": ""})

    if pipeline_mode == "Multi-Agent Pipeline":
        history[-1]["content"] = "⚖️ **VIDURA AI Multi-Agent Pipeline Active...**\n\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()

        history[-1]["content"] += "🔍 **Agent 1 (Research Counsel):** Analyzing statutory references & precedents...\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        research_out, _ = call_llm("You are Agent 1: Senior Legal Researcher. Extract core legal issues, relevant statutes, and precedents.", input_payload, "llama-3.1-8b-instant")
        history[-1]["content"] += "✓ Statutory research complete.\n\n"
        
        history[-1]["content"] += "🛡️ **Agent 2 (Risk & Compliance Analyst):** Evaluating procedural and financial exposure...\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        risk_out, _ = call_llm("You are Agent 2: Risk Analyst. Identify legal liabilities, procedural hurdles, and evidentiary weaknesses.", f"QUERY:\n{input_payload}\nRESEARCH:\n{research_out}", "llama-3.1-8b-instant")
        history[-1]["content"] += "✓ Exposure assessment complete.\n\n"
        
        history[-1]["content"] += "🏛️ **Agent 3 (Senior Partner):** Synthesizing corporate legal draft...\n\n---\n\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        # Using openai/gpt-oss-120b for heavy high-powered reasoning
        final_out, _ = call_llm("You are Agent 3: Senior Partner at an elite law firm. Synthesize research and risk analysis into a highly professional legal opinion or draft using clear Markdown headers.", f"CONTEXT:\n{input_payload}\nRESEARCH:\n{research_out}\nRISKS:\n{risk_out}", "openai/gpt-oss-120b")
        
        for token in re.split(r'(\s+)', final_out or "Analysis failed."):
            history[-1]["content"] += token
            yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
            time.sleep(0.008)
    else:
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        res_text, _ = call_llm("You are VIDURA AI, Senior Corporate Counsel. Structure your response professionally using Markdown headers.", input_payload, "openai/gpt-oss-120b")
        for token in re.split(r'(\s+)', res_text or "Analysis failed."):
            history[-1]["content"] += token
            yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
            time.sleep(0.01)

    chats_store[active_title] = list(history)
    if user_email: save_chat_to_cloud(user_email, active_title, list(history))

    yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(choices=list(chats_store.keys()), value=active_title)

def load_past_chat(selected_title, chats_store):
    if selected_title in chats_store: 
        return sanitize_history(chats_store[selected_title]), selected_title
    return [], ""

def start_new_chat():
    return [], None, gr.update(visible=False), "", gr.update(value=None)

def handle_upload(file):
    if file: 
        filename = os.path.basename(file.name)
        chip_html = f"<div class='file-chip'><span>📄</span> <strong>{filename}</strong></div>"
        return file.name, gr.update(value=chip_html, visible=True)
    return None, gr.update(visible=False)

# ═══════════════════════════════════════════════════════════════════
# 4. EXECUTIVE CORPORATE STYLING & CUSTOM JS SCRIPT INJECTION
# ═══════════════════════════════════════════════════════════════════

css_code = """
/* Executive Dark Palette */
:root { 
    --bg-main: #0A0E17; 
    --sidebar-bg: #111622; 
    --card-bg: #161C2A; 
    --border-color: #232D3F;
    --text-primary: #F0F4F8; 
    --text-muted: #8E9BAE;
    --accent-gold: #C5A059;
}

body, .gradio-container { background-color: var(--bg-main) !important; color: var(--text-primary) !important; font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important; margin: 0 !important; padding: 0 !important; }
footer { display: none !important; }

/* Strip Default Containers */
.panel, .contain, .box, .wrap, .gr-box, .gr-panel, .form { border: none !important; box-shadow: none !important; background: transparent !important; margin: 0 !important; }
#chatbot { border: none !important; background: transparent !important; box-shadow: none !important; }
.chatbot-container { padding-bottom: 95px !important; }

/* Corporate Sidebar */
.gr-sidebar { background-color: var(--sidebar-bg) !important; border-right: 1px solid var(--border-color) !important; padding: 18px !important; height: 100vh !important; }
.brand-header { display: flex; align-items: center; gap: 10px; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color); }
.brand-title { font-size: 1.25rem; font-weight: 700; color: #FFF; letter-spacing: 0.5px; }
.brand-badge { font-size: 0.65rem; background: rgba(197, 160, 89, 0.15); color: var(--accent-gold); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(197, 160, 89, 0.3); font-weight: 600; }

.new-chat-btn button { background: var(--card-bg) !important; color: var(--text-primary) !important; border: 1px solid var(--border-color) !important; border-radius: 10px !important; font-weight: 600 !important; padding: 10px 14px !important; transition: all 0.2s ease; width: 100%; text-align: left !important; }
.new-chat-btn button:hover { border-color: var(--accent-gold) !important; background: #1C2436 !important; }

#history-list { border: none !important; background: transparent !important; }
#history-list label { padding: 10px 12px !important; border-radius: 8px !important; cursor: pointer; transition: 0.2s; margin-bottom: 3px; font-size: 0.88rem; color: var(--text-muted) !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#history-list label:hover { background: #1C2436 !important; color: #FFF !important; }
#history-list input[type="radio"] { display: none !important; }

/* Chat Bubbles */
.message-wrap .message { border: none !important; box-shadow: none !important; font-size: 1rem !important; color: var(--text-primary) !important; line-height: 1.6; }
.message-wrap .bot, .message-wrap .assistant { padding: 16px 0 !important; }
.message-wrap .user { background: var(--card-bg) !important; border: 1px solid var(--border-color) !important; border-radius: 18px !important; padding: 12px 20px !important; margin-bottom: 12px; max-width: 75%; float: right; clear: both; }

/* Floating Executive Input Bar */
#input-container { background: var(--card-bg); border-radius: 24px; padding: 6px 14px; display: flex; align-items: center; width: 100%; max-width: 850px; margin: 0 auto !important; position: sticky; bottom: 24px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); border: 1px solid var(--border-color) !important; z-index: 100; transition: border-color 0.2s ease; }
#input-container:focus-within { border-color: var(--accent-gold) !important; }

#msg-input textarea { background: transparent !important; border: none !important; box-shadow: none !important; font-size: 0.98rem !important; padding: 10px !important; color: var(--text-primary) !important; max-height: 150px; }

/* 🔥 HIDE GRADIO ARTIFACTS 🔥 */
.hidden-audio-bridge { display: none !important; }

/* 🔥 CLEAN CSS BACKGROUND ICONS FOR UPLOAD, MIC, AND SEND 🔥 */
#upload-btn, #mic-btn, #send-btn { background-color: transparent !important; border: none !important; width: 38px !important; height: 38px !important; min-width: 38px !important; cursor: pointer !important; border-radius: 10px !important; transition: all 0.2s ease !important; color: transparent !important; box-shadow: none !important; }
#upload-btn button, #upload-btn label { color: transparent !important; }

#upload-btn { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238E9BAE' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48'/%3E%3C/svg%3E") !important; background-repeat: no-repeat !important; background-position: center !important; background-size: 18px 18px !important; }
#upload-btn:hover { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23C5A059' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48'/%3E%3C/svg%3E") !important; background-color: #232D3F !important; }

#mic-btn { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238E9BAE' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z'/%3E%3Cpath d='M19 10v2a7 7 0 0 1-14 0v-2'/%3E%3Cline x1='12' y1='19' x2='12' y2='22'/%3E%3C/svg%3E") !important; background-repeat: no-repeat !important; background-position: center !important; background-size: 18px 18px !important; }
#mic-btn:hover { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23C5A059' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z'/%3E%3Cpath d='M19 10v2a7 7 0 0 1-14 0v-2'/%3E%3Cline x1='12' y1='19' x2='12' y2='22'/%3E%3C/svg%3E") !important; background-color: #232D3F !important; }

/* Mic Active Recording Pulse */
#mic-btn.recording { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23EF4444' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z'/%3E%3Cpath d='M19 10v2a7 7 0 0 1-14 0v-2'/%3E%3Cline x1='12' y1='19' x2='12' y2='22'/%3E%3C/svg%3E") !important; background-color: rgba(239, 68, 68, 0.15) !important; animation: pulse-ring 1.5s infinite; }
@keyframes pulse-ring { 0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); } 70% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); } 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); } }

#send-btn { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238E9BAE' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='22' y1='2' x2='11' y2='13'/%3E%3Cpolygon points='22 2 15 22 11 13 2 9 22 2'/%3E%3C/svg%3E") !important; background-repeat: no-repeat !important; background-position: center !important; background-size: 18px 18px !important; }
#send-btn:hover { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23C5A059' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='22' y1='2' x2='11' y2='13'/%3E%3Cpolygon points='22 2 15 22 11 13 2 9 22 2'/%3E%3C/svg%3E") !important; background-color: #232D3F !important; }

.file-chip { display: inline-flex; align-items: center; gap: 8px; background: rgba(197, 160, 89, 0.12); border: 1px solid rgba(197, 160, 89, 0.3); color: var(--accent-gold); padding: 6px 14px; border-radius: 20px; font-size: 0.82rem; margin-bottom: 10px; margin-left: 20px; }
#model-selector { border: none !important; background: transparent !important; min-width: 145px; }
#model-selector * { border: none !important; background: transparent !important; color: var(--text-muted) !important; font-size: 0.82rem !important; font-weight: 500; }
.login-link { display: block; text-align: center; background: linear-gradient(135deg, #C5A059, #D4AF37); color: #0A0E17 !important; padding: 10px; border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 0.88rem; margin-top: 10px; transition: 0.2s; }
.login-link:hover { opacity: 0.9; }
.logout-link { display: block; text-align: center; background: #232D3F; color: var(--text-muted) !important; padding: 8px; border-radius: 8px; text-decoration: none; font-size: 0.82rem; margin-top: 10px; transition: 0.2s; }
.logout-link:hover { background: #2C384E; color: #FFF !important; }
"""

# 🔥 DIRECT JS TO PYTHON AUDIO BRIDGE 🔥
js_script = """
<script>
let customMediaRecorder;
let audioChunks = [];
let isRecording = false;
window.lastRecordedAudioBase64 = "";

async function toggleDictation() {
    const micBtn = document.querySelector("#mic-btn");
    const inputArea = document.querySelector("#msg-input textarea") || document.querySelector("#msg-input input");

    if (isRecording) {
        customMediaRecorder.stop();
        if (micBtn) micBtn.classList.remove("recording");
        if (inputArea) inputArea.placeholder = "Processing voice...";
        isRecording = false;
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        customMediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        customMediaRecorder.ondataavailable = event => {
            audioChunks.push(event.data);
        };

        customMediaRecorder.onstop = () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            const reader = new FileReader();
            reader.readAsDataURL(audioBlob);
            reader.onloadend = () => {
                window.lastRecordedAudioBase64 = reader.result;
                const hiddenBtn = document.querySelector("#hidden-submit-btn");
                if (hiddenBtn) hiddenBtn.click();
                if (inputArea) inputArea.placeholder = "Ask VIDURA AI or dictate query...";
            };
            stream.getTracks().forEach(track => track.stop());
        };

        customMediaRecorder.start();
        if (micBtn) micBtn.classList.add("recording");
        if (inputArea) inputArea.placeholder = "Listening... (Click mic again to stop)";
        isRecording = true;

    } catch (err) {
        console.error("Mic access denied:", err);
        alert("Microphone access is required for dictation. Please allow it in your browser settings.");
    }
}
</script>
"""

with gr.Blocks(title="VIDURA AI — Corporate Counsel", fill_width=True) as demo:
    gr.HTML(js_script)
    
    chats_store = gr.State({})
    active_title = gr.State("")
    user_email_state = gr.State("")
    uploaded_file_state = gr.State(None)

    with gr.Row():
        with gr.Column(scale=2, elem_classes="gr-sidebar", min_width=260):
            gr.HTML("""
                <div class="brand-header">
                    <span style="font-size: 1.4rem;">🏛️</span>
                    <div>
                        <div class="brand-title">VIDURA AI</div>
                        <div class="brand-badge">ENTERPRISE COUNSEL</div>
                    </div>
                </div>
            """)
            
            new_chat_btn = gr.Button("➕ New Legal Matter", elem_classes="new-chat-btn")
            gr.Markdown("<br><span style='color: #8E9BAE; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.5px;'>RECENT MATTERS</span>")
            history_list = gr.Radio(choices=[], label="", container=False, interactive=True, elem_id="history-list")
            gr.Markdown("<br><span style='color: #8E9BAE; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.5px;'>COUNSEL ACCOUNT</span>")
            login_html = gr.HTML('<a href="/login" target="_top" class="login-link">🌐 Sign in with Google</a>')
            profile_html = gr.HTML("")
            logout_html = gr.HTML('<a href="/logout" target="_top" class="logout-link">Sign Out</a>', visible=False)

        with gr.Column(scale=9, elem_classes="chatbot-container"):
            chatbot = gr.Chatbot(label="", height="calc(100vh - 120px)", show_label=False, avatar_images=(None, "🏛️"), elem_id="chatbot")
            file_display = gr.HTML("", visible=False)
            
            with gr.Row(elem_id="input-container"):
                file_btn = gr.UploadButton(label=" ", file_types=[".pdf", ".docx"], elem_id="upload-btn")
                mic_btn = gr.Button(value=" ", elem_id="mic-btn")
                msg_input = gr.Textbox(placeholder="Ask VIDURA AI or dictate query...", show_label=False, container=False, scale=6, elem_id="msg-input")
                pipeline_selector = gr.Dropdown(choices=["Fast Mode", "Multi-Agent Pipeline"], value="Multi-Agent Pipeline", show_label=False, container=False, scale=2, elem_id="model-selector")
                send_btn = gr.Button(value=" ", variant="primary", scale=1, elem_id="send-btn")
                
            hidden_btn = gr.Button(elem_id="hidden-submit-btn", visible=False)

    def load_user_profile_and_history(request: gr.Request):
        user = request.request.session.get('user') if request else None
        if user:
            name = user.get('name', 'Counsel')
            email = user.get('email', '')
            pic = user.get('picture', '') or "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"

            cloud_chats = fetch_user_chats_from_cloud(email)
            chat_choices = list(cloud_chats.keys()) if cloud_chats else []

            profile_card = f"<div style='display:flex; align-items:center; gap:10px; padding: 8px; border-radius: 8px; background: #161C2A; border: 1px solid #232D3F;'><img src='{pic}' style='width:30px; height:30px; border-radius:50%;'><div><div style='font-weight:600; font-size:0.82rem; color:#F0F4F8;'>{name}</div><div style='font-size:0.7rem; color:#8E9BAE;'>{email}</div></div></div>"
            
            return (
                gr.update(visible=False), profile_card, gr.update(visible=True, value='<a href="/logout" target="_top" class="logout-link">Sign Out</a>'), 
                cloud_chats, gr.update(choices=chat_choices, value=None), email, "", [] 
            )
        return gr.update(visible=True), "", gr.update(visible=False), {}, gr.update(choices=[], value=None), "", "", []

    mic_btn.click(fn=None, inputs=None, outputs=None, js="() => toggleDictation()")
    
    hidden_btn.click(
        fn=process_base64_audio, 
        inputs=[], 
        outputs=[msg_input], 
        js="() => { return window.lastRecordedAudioBase64 || ''; }"
    )

    file_btn.upload(fn=handle_upload, inputs=[file_btn], outputs=[uploaded_file_state, file_display])

    demo.load(fn=load_user_profile_and_history, inputs=None, outputs=[login_html, profile_html, logout_html, chats_store, history_list, user_email_state, active_title, chatbot])
    
    chat_inputs = [msg_input, uploaded_file_state, pipeline_selector, chatbot, chats_store, active_title, user_email_state]
    chat_outputs = [msg_input, uploaded_file_state, file_display, chatbot, chats_store, active_title, history_list]
    
    msg_input.submit(fn=process_chat, inputs=chat_inputs, outputs=chat_outputs)
    send_btn.click(fn=process_chat, inputs=chat_inputs, outputs=chat_outputs)
    
    history_list.change(fn=load_past_chat, inputs=[history_list, chats_store], outputs=[chatbot, active_title])
    new_chat_btn.click(fn=start_new_chat, inputs=[], outputs=[chatbot, uploaded_file_state, file_display, active_title, history_list])

app = gr.mount_gradio_app(
    app, 
    demo.queue(), 
    path="/",
    allowed_paths=["/"],
    **{"css": css_code}
)

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
