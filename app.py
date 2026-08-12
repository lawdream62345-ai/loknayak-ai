# ═══════════════════════════════════════════════════════════════════
#  ⚖️ LOKNAYAK LEGAL AI — GRADIO 6.23+ IMMERSIVE GEMINI UI
# ═══════════════════════════════════════════════════════════════════

import gradio as gr
import requests
import time
import os
import re
import json
import PyPDF2
import docx
from google import genai
from google.genai import types

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

import firebase_admin
from firebase_admin import credentials, firestore

APP_NAME = "LokNayak Legal AI"
print("=" * 60)
print(f"  🚀 STARTING {APP_NAME} SERVER")
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
        # Connected using the custom 'default' database ID you created
        db = firestore.client(database_id="default")
        print("✅ Firestore Cloud Database Connected Successfully!")
    except Exception as e:
        print("⚠️ Firestore Initialization Warning:", e)
else:
    print("ℹ️ FIREBASE_CREDENTIALS_JSON not found. Running in Local Memory fallback mode.")

def sanitize_history(history_data):
    if not history_data: return []
    clean_history = []
    for item in history_data:
        if isinstance(item, dict):
            role = item.get("role", "assistant")
            if role in ["bot", "LOKNAYAK"]: role = "assistant"
            clean_history.append({"role": role, "content": item.get("content", "")})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            if item[0]: clean_history.append({"role": "user", "content": str(item[0])})
            if item[1]: clean_history.append({"role": "assistant", "content": str(item[1])})
    return clean_history

def save_chat_to_cloud(email, title, history):
    if not db or not email or not title:
        return
    try:
        safe_doc_id = re.sub(r'[^a-zA-Z0-9 _-]', '', title).strip()[:80]
        if not safe_doc_id: safe_doc_id = "Untitled_Case"
        
        doc_ref = db.collection("users").document(email).collection("chats").document(safe_doc_id)
        doc_ref.set({
            "title": title,
            "history": history,
            "updated_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
    except Exception as e:
        pass

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
        return {}

# ═══════════════════════════════════════════════════════════════════
# 2. FASTAPI & GOOGLE OAUTH SETUP (BULLETPROOF ROUTING)
# ═══════════════════════════════════════════════════════════════════
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="loknayak-secure-key-2026")

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get('OAUTH_CLIENT_ID', ''),
    client_secret=os.environ.get('OAUTH_CLIENT_SECRET', ''),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# 🔥 Accepts both GET and POST to prevent 405 errors across all devices
@app.api_route("/login", methods=["GET", "POST"])
async def login(request: Request):
    redirect_uri = request.url_for('auth')
    if "onrender.com" in str(redirect_uri): redirect_uri = str(redirect_uri).replace("http://", "https://")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.api_route("/auth", methods=["GET", "POST"])
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user: request.session['user'] = dict(user)
    except Exception as e:
        pass
    return RedirectResponse(url='/')

@app.api_route("/logout", methods=["GET", "POST"])
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')

# ═══════════════════════════════════════════════════════════════════
# 3. AI ENGINE & CHAT CONTROLLER
# ═══════════════════════════════════════════════════════════════════
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
        return f"[File Read Error]"

def call_llm(system_prompt, user_prompt, model_name="llama-3.1-8b-instant"):
    if GROQ_KEY:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={"model": model_name, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.2, "max_tokens": 1800},
                timeout=20
            )
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"], f"Groq ({model_name})"
        except Exception: pass

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
        memory_context = "--- PREVIOUS CONTEXT ---\n"
        for msg in history:
            role_str = "USER" if msg.get("role") == "user" else "LOKNAYAK"
            memory_context += f"{role_str}: {msg.get('content', '')}\n\n"

    display_msg = user_message
    if file_path: display_msg = f"📎 *[Document Attached]*\n\n" + user_message

    history.append({"role": "user", "content": display_msg})
    
    active_title = current_title if (current_title and current_title != "New Case") else (user_message[:30] + "..." if len(user_message) > 30 else "Doc Analysis")
    
    chats_store[active_title] = list(history)
    if user_email: save_chat_to_cloud(user_email, active_title, list(history))

    start_time = time.time()
    input_payload = f"{memory_context}\n--- CURRENT USER QUERY ---\n{user_message}\n"
    if doc_text: input_payload += f"\n--- ATTACHED DOC CONTEXT ---\n{doc_text}\n"

    history.append({"role": "assistant", "content": ""})

    if pipeline_mode == "Multi-Agent Pipeline (Deep)":
        history[-1]["content"] = "🤖 **Pipeline Initiated...**\n\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()

        history[-1]["content"] += "🔍 **Agent 1:** Analyzing statutes...\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        research_out, _ = call_llm("You are Agent 1: Researcher. Extract core legal issues.", input_payload, "llama-3.1-8b-instant")
        history[-1]["content"] += "✓ Research complete.\n\n"
        
        history[-1]["content"] += "⚖️ **Agent 2:** Evaluating risks...\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        risk_out, _ = call_llm("You are Agent 2: Risk Analyst. Identify legal risks.", f"QUERY:\n{input_payload}\nRESEARCH:\n{research_out}", "llama-3.1-8b-instant")
        history[-1]["content"] += "✓ Risk assessment complete.\n\n"
        
        history[-1]["content"] += "🏛️ **Agent 3:** Drafting analysis...\n\n---\n\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        final_out, _ = call_llm("You are Agent 3: Senior Counsel. Synthesize into Markdown.", f"CONTEXT:\n{input_payload}\nRESEARCH:\n{research_out}\nRISKS:\n{risk_out}", "llama-3.3-70b-versatile")
        
        for token in re.split(r'(\s+)', final_out or "Analysis failed."):
            history[-1]["content"] += token
            yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
            time.sleep(0.008)
    else:
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update()
        res_text, _ = call_llm("You are LokNayak AI. Use Markdown.", input_payload, "llama-3.3-70b-versatile")
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
    if file: return file.name, gr.update(value=f"📎 **Attached:** {os.path.basename(file.name)}", visible=True)
    return None, gr.update(visible=False)

# ═══════════════════════════════════════════════════════════════════
# 4. GRADIO UI LAYOUT & CSS (GEMINI IMMERSIVE STYLE)
# ═══════════════════════════════════════════════════════════════════

css_code = """
/* 1. Global Reset & Background (Midnight Blue/Black) */
:root { --bg-main: #0E1117; --sidebar-bg: #1A1C23; --card-bg: #1E1F20; --text-primary: #E3E3E3; --accent: #A8C7FA; }
body, .gradio-container { background-color: var(--bg-main) !important; color: var(--text-primary) !important; font-family: 'Google Sans', 'Inter', sans-serif !important; margin: 0 !important; padding: 0 !important; }
footer { display: none !important; }

/* 2. Strip ALL Gradio Box Artifacts */
.panel, .contain, .box, .wrap, .gr-box, .gr-panel, .form { border: none !important; box-shadow: none !important; background: transparent !important; margin: 0 !important; }
#chatbot { border: none !important; background: transparent !important; box-shadow: none !important; }
.chatbot-container { padding-bottom: 80px !important; }

/* 3. The Sidebar Styling */
.gr-sidebar { background-color: var(--sidebar-bg) !important; border-right: 1px solid #2B2C2E !important; padding: 15px !important; height: 100vh !important; }
.header-bar h1 { font-size: 1.4rem; font-weight: 600; color: #fff; margin: 0 0 20px 0; display: flex; align-items: center; gap: 8px;}
.new-chat-btn button { background: transparent !important; color: #fff !important; border: 1px solid #3c4043 !important; border-radius: 20px !important; font-weight: 500 !important; padding: 10px 15px !important; transition: 0.2s; text-align: left !important; width: 100%; display: flex; align-items: center; gap: 10px; }
.new-chat-btn button:hover { background: #2b2c2e !important; }

/* Sidebar History List */
#history-list { border: none !important; background: transparent !important; box-shadow: none !important; padding: 0 !important; }
#history-list label { padding: 10px !important; border-radius: 8px !important; cursor: pointer; transition: 0.2s; margin-bottom: 2px; font-size: 0.9rem; color: #C4C7C5 !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#history-list label:hover { background: #2B2C2E !important; color: #fff !important; }
#history-list input[type="radio"] { display: none !important; }

/* 4. Chat Bubbles (Gemini Style) */
.message-wrap .message { border: none !important; box-shadow: none !important; background: transparent !important; font-size: 1.05rem !important; color: #E3E3E3 !important; line-height: 1.6; }
.message-wrap .bot, .message-wrap .assistant { padding: 12px 0 !important; }
.message-wrap .user { background: var(--card-bg) !important; border-radius: 24px !important; padding: 12px 20px !important; margin-bottom: 10px; max-width: 75%; float: right; clear: both; }

/* 5. The Floating Input Bar */
#input-container { background: var(--card-bg); border-radius: 30px; padding: 8px 16px; display: flex; align-items: center; width: 100%; max-width: 800px; margin: 0 auto !important; position: sticky; bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border: 1px solid #3c4043 !important; z-index: 100; }
#msg-input textarea { background: transparent !important; border: none !important; box-shadow: none !important; font-size: 1rem !important; padding: 10px !important; color: #E3E3E3 !important; max-height: 150px; overflow-y: auto; }
#upload-btn, #send-btn { background: transparent !important; border: none !important; font-size: 1.3rem; padding: 0 !important; width: 40px !important; height: 40px !important; color: #A8C7FA !important; cursor: pointer; transition: 0.2s; }
#upload-btn:hover, #send-btn:hover { background: #2B2C2E !important; border-radius: 50% !important; }

/* Dropdown */
#model-selector { border: none !important; background: transparent !important; box-shadow: none !important; min-width: 150px; }
#model-selector * { border: none !important; background: transparent !important; box-shadow: none !important; color: #8E918F !important; font-size: 0.85rem !important; font-weight: 500; }
.form { background: transparent !important; }

/* 🔥 BULLETPROOF HTML LINKS FOR LOGIN/LOGOUT 🔥 */
.login-link { display: block; text-align: center; background: #A8C7FA; color: #131314 !important; padding: 10px; border-radius: 20px; text-decoration: none; font-weight: 600; margin-top: 10px; transition: 0.2s; }
.login-link:hover { background: #d3e3fd; }
.logout-link { display: block; text-align: center; background: #3C4043; color: #E3E3E3 !important; padding: 8px; border-radius: 20px; text-decoration: none; font-weight: 500; margin-top: 10px; transition: 0.2s; }
.logout-link:hover { background: #5f6368; }
"""

with gr.Blocks(title="LokNayak Legal AI", fill_width=True) as demo:
    chats_store = gr.State({})
    active_title = gr.State("")
    user_email_state = gr.State("")
    uploaded_file_state = gr.State(None)

    with gr.Row():
        with gr.Column(scale=2, elem_classes="gr-sidebar", min_width=250):
            gr.HTML("<div class='header-bar'><h1>✨ LokNayak</h1></div>")
            new_chat_btn = gr.Button("✏️ New chat", elem_classes="new-chat-btn")
            
            gr.Markdown("<br><span style='color: #8E918F; font-size: 0.8rem; font-weight: 600;'>Recent</span>")
            history_list = gr.Radio(choices=[], label="", container=False, interactive=True, elem_id="history-list")
            
            gr.Markdown("<br><span style='color: #8E918F; font-size: 0.8rem; font-weight: 600;'>Account</span>")
            
            # 🔥 Replaced buggy Gradio Buttons with raw HTML native browser links
            login_html = gr.HTML('<a href="/login" class="login-link">🌐 Sign in with Google</a>')
            profile_html = gr.HTML("")
            logout_html = gr.HTML('<a href="/logout" class="logout-link">Log Out</a>', visible=False)

        with gr.Column(scale=9, elem_classes="chatbot-container"):
            chatbot = gr.Chatbot(label="", height="calc(100vh - 120px)", show_label=False, avatar_images=(None, "✨"), elem_id="chatbot")
            
            file_display = gr.Markdown("", visible=False)
            
            with gr.Row(elem_id="input-container"):
                file_btn = gr.UploadButton("➕", file_types=[".pdf", ".docx"], elem_id="upload-btn")
                msg_input = gr.Textbox(placeholder="Ask LokNayak...", show_label=False, container=False, scale=6, elem_id="msg-input")
                pipeline_selector = gr.Dropdown(choices=["Fast Mode", "Multi-Agent Pipeline"], value="Multi-Agent Pipeline", show_label=False, container=False, scale=2, elem_id="model-selector")
                send_btn = gr.Button("🚀", variant="primary", scale=1, elem_id="send-btn")


    def load_user_profile_and_history(request: gr.Request):
        user = request.request.session.get('user') if request else None
        if user:
            name = user.get('name', 'Counsel')
            email = user.get('email', '')
            pic = user.get('picture', '') or "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"

            cloud_chats = fetch_user_chats_from_cloud(email)
            chat_choices = list(cloud_chats.keys()) if cloud_chats else []
            latest_title = chat_choices[0] if chat_choices else ""
            latest_history = cloud_chats.get(latest_title, []) if latest_title else []

            html = f"<div style='display:flex; align-items:center; gap:10px; padding: 10px; border-radius: 8px; cursor: pointer;' onmouseover=\"this.style.background='#2b2c2e'\" onmouseout=\"this.style.background='transparent'\"><img src='{pic}' style='width:32px; height:32px; border-radius:50%;'><div><div style='font-weight:500; font-size:0.85rem; color:#e3e3e3;'>{name}</div></div></div>"
            
            return (
                gr.update(visible=False), html, gr.update(visible=True), cloud_chats, 
                gr.update(choices=chat_choices, value=latest_title if latest_title else None),
                email, latest_title, latest_history
            )
        return gr.update(visible=True), "", gr.update(visible=False), {}, gr.update(choices=[], value=None), "", "", []

    file_btn.upload(fn=handle_upload, inputs=[file_btn], outputs=[uploaded_file_state, file_display])

    demo.load(fn=load_user_profile_and_history, inputs=None, outputs=[login_html, profile_html, logout_html, chats_store, history_list, user_email_state, active_title, chatbot])
    
    chat_inputs = [msg_input, uploaded_file_state, pipeline_selector, chatbot, chats_store, active_title, user_email_state]
    chat_outputs = [msg_input, uploaded_file_state, file_display, chatbot, chats_store, active_title, history_list]
    
    msg_input.submit(fn=process_chat, inputs=chat_inputs, outputs=chat_outputs)
    send_btn.click(fn=process_chat, inputs=chat_inputs, outputs=chat_outputs)
    
    history_list.change(fn=load_past_chat, inputs=[history_list, chats_store], outputs=[chatbot, active_title])
    new_chat_btn.click(fn=start_new_chat, inputs=[], outputs=[chatbot, uploaded_file_state, file_display, active_title, history_list])

# ═══════════════════════════════════════════════════════════════════
# 5. STARTUP HANDLER (Gradio 6 CSS Injection)
# ═══════════════════════════════════════════════════════════════════
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="loknayak-secure-key-2026")

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
