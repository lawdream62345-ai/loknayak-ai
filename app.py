# ═══════════════════════════════════════════════════════════════════
#  ⚖️ LOKNAYAK LEGAL AI — GEMINI UI EDITION (FIRESTORE CLOUD SYNC)
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
        db = firestore.client()
        print("✅ Firestore Cloud Database Connected Successfully!")
    except Exception as e:
        print("⚠️ Firestore Initialization Warning:", e)
else:
    print("ℹ️ FIREBASE_CREDENTIALS_JSON not found. Running in Local Memory fallback mode.")

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
        user_chats = {item["title"]: item["history"] for item in chat_data}
        return user_chats
    except Exception as e:
        return {}

# ═══════════════════════════════════════════════════════════════════
# 2. FASTAPI & GOOGLE OAUTH SETUP
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

@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth')
    if "onrender.com" in str(redirect_uri): redirect_uri = str(redirect_uri).replace("http://", "https://")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth")
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user: request.session['user'] = dict(user)
    except Exception as e:
        pass
    return RedirectResponse(url='/')

@app.get("/logout")
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
        yield "", file_path, gr.update(), history, chats_store, current_title, gr.update(), "⚠️ Type a query."
        return

    doc_text = parse_file(file_path) if file_path else ""
    if len(doc_text) > 20000: doc_text = doc_text[:20000]

    memory_context = ""
    if history:
        memory_context = "--- PREVIOUS CONTEXT ---\n"
        for u_msg, b_msg in history:
            if u_msg: memory_context += f"USER: {u_msg}\n\n"
            if b_msg: memory_context += f"LOKNAYAK: {b_msg}\n\n"

    display_msg = user_message
    if file_path: display_msg = f"📎 *[Document Attached]*\n\n" + user_message

    history.append([display_msg, ""])
    active_title = current_title if (current_title and current_title != "New Case") else (user_message[:30] + "..." if len(user_message) > 30 else "Doc Analysis")
    
    chats_store[active_title] = list(history)
    if user_email: save_chat_to_cloud(user_email, active_title, list(history))

    start_time = time.time()
    input_payload = f"{memory_context}\n--- CURRENT USER QUERY ---\n{user_message}\n"
    if doc_text: input_payload += f"\n--- ATTACHED DOC CONTEXT ---\n{doc_text}\n"

    if pipeline_mode == "Multi-Agent Pipeline (Deep)":
        history[-1][1] = "🤖 **Pipeline Initiated...**\n\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(), "Working..."

        history[-1][1] += "🔍 **Agent 1:** Analyzing statutes...\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(), "Agent 1..."
        research_out, _ = call_llm("You are Agent 1: Researcher. Extract core legal issues.", input_payload, "llama-3.1-8b-instant")
        history[-1][1] += "✓ Research complete.\n\n"
        
        history[-1][1] += "⚖️ **Agent 2:** Evaluating risks...\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(), "Agent 2..."
        risk_out, _ = call_llm("You are Agent 2: Risk Analyst. Identify legal risks.", f"QUERY:\n{input_payload}\nRESEARCH:\n{research_out}", "llama-3.1-8b-instant")
        history[-1][1] += "✓ Risk assessment complete.\n\n"
        
        history[-1][1] += "🏛️ **Agent 3:** Drafting analysis...\n\n---\n\n"
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(), "Agent 3..."
        final_out, _ = call_llm("You are Agent 3: Senior Counsel. Synthesize into Markdown.", f"CONTEXT:\n{input_payload}\nRESEARCH:\n{research_out}\nRISKS:\n{risk_out}", "llama-3.3-70b-versatile")
        
        for token in re.split(r'(\s+)', final_out or "Analysis failed."):
            history[-1][1] += token
            yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(), "Finalizing..."
            time.sleep(0.008)
    else:
        yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(), "Thinking..."
        res_text, _ = call_llm("You are LokNayak AI. Use Markdown.", input_payload, "llama-3.3-70b-versatile")
        for token in re.split(r'(\s+)', res_text or "Analysis failed."):
            history[-1][1] += token
            yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(), "Typing..."
            time.sleep(0.01)

    chats_store[active_title] = list(history)
    if user_email: save_chat_to_cloud(user_email, active_title, list(history))

    yield "", None, gr.update(visible=False), history, chats_store, active_title, gr.update(choices=list(chats_store.keys()), value=active_title), f"⚡ Done in {round(time.time() - start_time, 1)}s"

def load_past_chat(selected_title, chats_store):
    if selected_title in chats_store: return chats_store[selected_title], selected_title, "Loaded chat"
    return [], "", "Ready"

def start_new_chat():
    return [], None, gr.update(visible=False), "", gr.update(value=None), "New chat started"

def handle_upload(file):
    if file: return file.name, gr.update(value=f"📎 **Attached:** {os.path.basename(file.name)}", visible=True)
    return None, gr.update(visible=False)

# ═══════════════════════════════════════════════════════════════════
# 4. GRADIO UI LAYOUT (GEMINI STYLE)
# ═══════════════════════════════════════════════════════════════════
custom_css = """
/* Core Backgrounds */
:root { --bg-main: #131314; --card-bg: #1e1f20; --text-primary: #e3e3e3; --accent: #a8c7fa; }
body, .gradio-container { background-color: var(--bg-main) !important; color: var(--text-primary) !important; font-family: 'Google Sans', 'Inter', sans-serif !important; }
.gradio-container { max-width: 1200px !important; margin: 0 auto !important; }

/* Hide Footer */
footer { display: none !important; }

/* 1. Sidebar Elements */
.header-bar h1 { font-size: 1.6rem; font-weight: 600; background: linear-gradient(135deg, #a8c7fa, #d3e3fd); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
.new-chat-btn button { background: #1e1f20 !important; color: #a8c7fa !important; border: none !important; border-radius: 20px !important; font-weight: 600 !important; padding: 10px !important; transition: 0.2s;}
.new-chat-btn button:hover { background: #2b2c2e !important; }
.profile-card { background: #1e1f20; border-radius: 12px; padding: 12px; margin-top: 10px; border: none; }

/* 2. The History List (Replaces Dropdown) */
#history-list { border: none !important; background: transparent !important; box-shadow: none !important; }
#history-list label { padding: 10px !important; border-radius: 8px !important; cursor: pointer; transition: 0.2s; margin-bottom: 2px; }
#history-list label:hover { background: #2b2c2e !important; }
#history-list input[type="radio"] { display: none !important; } /* Hides the radio circle */

/* 3. Borderless Chatbot (Gemini Style) */
#chatbot { border: none !important; background: transparent !important; box-shadow: none !important; }
.message-wrap .message { border: none !important; box-shadow: none !important; background: transparent !important; font-size: 1rem !important; }
.message-wrap .user { background: #1e1f20 !important; border-radius: 24px !important; padding: 12px 20px !important; margin-bottom: 10px; border: none !important; max-width: 75%; }
.message-wrap .bot { background: transparent !important; padding: 12px 0 !important; border: none !important; }

/* 4. The Input Bar (Gemini Style) */
#input-container { background: #1e1f20; border-radius: 30px; padding: 5px 10px; align-items: center; }
#msg-input textarea { background: transparent !important; border: none !important; box-shadow: none !important; font-size: 1rem !important; padding: 10px !important; }
#upload-btn { background: transparent !important; border: none !important; font-size: 1.4rem; padding: 0 !important; color: #a8c7fa !important; width: 40px !important; height: 40px !important; min-width: 40px !important; box-shadow: none !important; }
#send-btn { background: transparent !important; border: none !important; font-size: 1.4rem; padding: 0 !important; width: 40px !important; height: 40px !important; min-width: 40px !important; box-shadow: none !important; }
#upload-btn:hover, #send-btn:hover { background: #2b2c2e !important; border-radius: 50% !important; }

/* Model Dropdown inside Input Row */
#model-selector { border: none !important; background: #2b2c2e !important; border-radius: 12px !important; box-shadow: none !important; }
#model-selector .wrap { border: none !important; background: transparent !important; box-shadow: none !important; }
"""

with gr.Blocks(title="LokNayak Legal AI", css=custom_css) as demo:
    chats_store = gr.State({})
    active_title = gr.State("")
    user_email_state = gr.State("")
    uploaded_file_state = gr.State(None)

    with gr.Sidebar(label="LokNayak Navigation"):
        gr.HTML("<div class='header-bar'><h1>LokNayak AI</h1></div>")
        new_chat_btn = gr.Button("➕ New Chat", elem_classes="new-chat-btn")
        
        gr.Markdown("### 📜 Past Cases")
        # History is now a sleek clickable sidebar list instead of a dropdown!
        history_list = gr.Radio(choices=[], label="", container=False, interactive=True, elem_id="history-list")
        
        gr.Markdown("---")
        gr.Markdown("### 👤 Account")
        login_btn = gr.Button("🌐 Sign in", variant="primary", link="/login")
        profile_html = gr.HTML("")
        logout_btn = gr.Button("Log Out", variant="secondary", link="/logout", visible=False)

    with gr.Column():
        chatbot = gr.Chatbot(label="", height=550, show_label=False, avatar_images=(None, "🏛️"), elem_id="chatbot")
        
        file_display = gr.Markdown("", visible=False) # Shows file name when attached
        
        # New Gemini-Style Input Row
        with gr.Row(elem_id="input-container"):
            # ➕ Plus Button for files
            file_btn = gr.UploadButton("➕", file_types=[".pdf", ".docx"], elem_id="upload-btn")
            
            msg_input = gr.Textbox(placeholder="Ask a legal question...", show_label=False, container=False, scale=6, elem_id="msg-input")
            
            # Model Selector next to the text box
            pipeline_selector = gr.Dropdown(choices=["Fast Mode (Single AI)", "Multi-Agent Pipeline (Deep)"], value="Multi-Agent Pipeline (Deep)", show_label=False, container=False, scale=2, elem_id="model-selector")
            
            send_btn = gr.Button("🚀", variant="primary", scale=1, elem_id="send-btn")

    status_text = gr.HTML("<div style='text-align:center; font-size:0.75rem; color:#8e918f; margin-top:8px;'>Outputs must be reviewed by an attorney.</div>")

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

            html = f"<div class='profile-card'><div style='display:flex; align-items:center; gap:10px;'><img src='{pic}' style='width:35px; height:35px; border-radius:50%;'><div><div style='font-weight:600; font-size:0.85rem; color:#e3e3e3;'>{name}</div><div style='font-size:0.7rem; color:#a8c7fa;'>{email}</div></div></div></div>"
            
            return (
                gr.update(visible=False), html, gr.update(visible=True), cloud_chats, 
                gr.update(choices=chat_choices, value=latest_title if latest_title else None),
                email, latest_title, latest_history
            )
        return gr.update(visible=True), "", gr.update(visible=False), {}, gr.update(choices=[], value=None), "", "", []

    # Upload Handler
    file_btn.upload(fn=handle_upload, inputs=[file_btn], outputs=[uploaded_file_state, file_display])

    demo.load(fn=load_user_profile_and_history, inputs=None, outputs=[login_btn, profile_html, logout_btn, chats_store, history_list, user_email_state, active_title, chatbot])
    
    chat_inputs = [msg_input, uploaded_file_state, pipeline_selector, chatbot, chats_store, active_title, user_email_state]
    chat_outputs = [msg_input, uploaded_file_state, file_display, chatbot, chats_store, active_title, history_list, status_text]
    
    msg_input.submit(fn=process_chat, inputs=chat_inputs, outputs=chat_outputs)
    send_btn.click(fn=process_chat, inputs=chat_inputs, outputs=chat_outputs)
    
    history_list.change(fn=load_past_chat, inputs=[history_list, chats_store], outputs=[chatbot, active_title, status_text])
    new_chat_btn.click(fn=start_new_chat, inputs=[], outputs=[chatbot, uploaded_file_state, file_display, active_title, history_list, status_text])

# ═══════════════════════════════════════════════════════════════════
# 5. STARTUP HANDLER
# ═══════════════════════════════════════════════════════════════════
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
