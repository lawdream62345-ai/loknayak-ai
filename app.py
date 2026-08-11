# ═══════════════════════════════════════════════════════════════════
#  ⚖️ LOKNAYAK LEGAL AI — ENTERPRISE EDITION
#  Hybrid Multi-Agent | FastAPI Backend | Native Google OAuth
# ═══════════════════════════════════════════════════════════════════

import gradio as gr
import requests
import time
import os
import re
import PyPDF2
import docx
from google import genai
from google.genai import types

# ─── NEW SERVER IMPORTS ───
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

APP_NAME = "LokNayak Legal AI"
print("=" * 60)
print(f"  🚀 STARTING {APP_NAME} SERVER")
print("=" * 60)

GROQ_KEY = os.environ.get("GROQ_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

# ═══════════════════════════════════════════════════════════════════
# 1. FASTAPI & GOOGLE OAUTH SETUP
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
    # Render forces HTTPS, so we ensure the redirect URL matches
    if "onrender.com" in str(redirect_uri):
        redirect_uri = str(redirect_uri).replace("http://", "https://")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth")
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user:
            request.session['user'] = dict(user)
    except Exception as e:
        print("Auth error:", e)
    return RedirectResponse(url='/')

@app.get("/logout")
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')


# ═══════════════════════════════════════════════════════════════════
# 2. AI ENGINE & CHAT LOGIC
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
        return f"[File Read Error: {str(e)}]"

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

def process_chat(user_message, file_obj, pipeline_mode, history, chats_store, current_title):
    if not user_message.strip() and not file_obj:
        yield "", history, chats_store, gr.update(), "⚠️ Please type a query or attach a document."
        return

    doc_text = parse_file(file_obj) if file_obj else ""
    if len(doc_text) > 20000: doc_text = doc_text[:20000]

    display_msg = user_message
    if file_obj: display_msg = f"📎 *[Attached: {os.path.basename(file_obj)}]*\n\n" + user_message

    history.append({"role": "user", "content": display_msg})
    active_title = current_title if (current_title and current_title != "New Case") else (user_message[:30] + "..." if len(user_message) > 30 else (user_message or "Doc Analysis"))
    start_time = time.time()
    input_payload = f"USER QUERY:\n{user_message}\n" + (f"\nATTACHED DOC:\n{doc_text}\n" if doc_text else "")

    if pipeline_mode == "Multi-Agent Pipeline (Deep)":
        history.append({"role": "assistant", "content": "🤖 **LokNayak Multi-Agent Pipeline Initiated...**\n\n"})
        yield "", history, chats_store, gr.update(), "Initiating Pipeline..."

        history[-1]["content"] += "🔍 **Agent 1 (Research):** Extracting relevant statutes & principles...\n"
        yield "", history, chats_store, gr.update(), "Agent 1 Working..."
        research_out, p1 = call_llm("You are Agent 1: Legal Researcher. Extract core legal issues, statutes, and precedents.", input_payload, "llama-3.1-8b-instant")
        if not research_out:
            history[-1]["content"] += "\n❌ Pipeline Error: Engine unavailable."
            yield "", history, chats_store, gr.update(), "Failed"
            return
        history[-1]["content"] += f"✓ Research completed ({p1}).\n\n"
        yield "", history, chats_store, gr.update(), "Agent 2 Working..."

        history[-1]["content"] += "⚖️ **Agent 2 (Risk Analyst):** Evaluating liabilities and procedural weaknesses...\n"
        risk_out, _ = call_llm("You are Agent 2: Risk Analyst. Identify legal risks, evidentiary hurdles, and procedural weaknesses.", f"QUERY:\n{input_payload}\nRESEARCH:\n{research_out}", "llama-3.1-8b-instant")
        history[-1]["content"] += "✓ Risk assessment completed.\n\n"
        yield "", history, chats_store, gr.update(), "Agent 3 Synthesizing..."

        history[-1]["content"] += "🏛️ **Agent 3 (Senior Counsel):** Finalizing legal analysis...\n\n---\n\n"
        final_out, _ = call_llm("You are Agent 3: Senior Counsel. Synthesize findings into a final legal draft using Markdown headers (ISSUE, ANALYSIS, RECOMMENDATION). End with an AI disclaimer.", f"CONTEXT:\n{input_payload}\nRESEARCH:\n{research_out}\nRISKS:\n{risk_out}", "llama-3.3-70b-versatile")
        
        for token in re.split(r'(\s+)', final_out or "Analysis failed."):
            history[-1]["content"] += token
            yield "", history, chats_store, gr.update(), "Finalizing..."
            time.sleep(0.008)
    else:
        history.append({"role": "assistant", "content": ""})
        yield "", history, chats_store, gr.update(), "Thinking..."
        res_text, _ = call_llm("You are LokNayak, Senior Legal Counsel AI. Structure response using Markdown (ISSUE, ANALYSIS, RECOMMENDATION). End with AI disclaimer.", input_payload, "llama-3.3-70b-versatile")
        for token in re.split(r'(\s+)', res_text or "Analysis failed."):
            history[-1]["content"] += token
            yield "", history, chats_store, gr.update(), "Typing..."
            time.sleep(0.01)

    chats_store[active_title] = list(history)
    yield "", history, chats_store, gr.update(choices=list(chats_store.keys()), value=active_title), f"⚡ Processed in {round(time.time() - start_time, 1)}s"

def load_past_chat(selected_title, chats_store):
    if selected_title in chats_store: return chats_store[selected_title], selected_title, f"Loaded past chat: {selected_title}"
    return [], "", "Ready"

def start_new_chat():
    return [], None, "", gr.update(value=None), "Started new chat session."


# ═══════════════════════════════════════════════════════════════════
# 3. GRADIO UI LAYOUT
# ═══════════════════════════════════════════════════════════════════
custom_css = """
:root { --bg-main: #131314; --card-bg: #1e1f20; --text-primary: #e3e3e3; --text-muted: #8e918f; --accent: #a8c7fa; }
body, .gradio-container { background-color: var(--bg-main) !important; color: var(--text-primary) !important; font-family: 'Google Sans', 'Inter', sans-serif !important; }
.gradio-container { max-width: 1200px !important; margin: 0 auto !important; }
.header-bar { text-align: center; padding: 15px 0 5px 0; }
.header-bar h1 { font-size: 1.8rem; font-weight: 600; background: linear-gradient(135deg, #a8c7fa, #d3e3fd); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
.new-chat-btn button { background: #2b2c2e !important; color: #a8c7fa !important; border: 1px solid #3c4043 !important; border-radius: 20px !important; font-weight: 600 !important; }
.profile-card { background: #2b2c2e; border-radius: 12px; padding: 12px; margin-top: 10px; border: 1px solid #3c4043; }
footer { display: none !important; }
"""

with gr.Blocks(title="LokNayak Legal AI") as demo:
    chats_store = gr.State({})
    active_title = gr.State("")

    with gr.Sidebar(label="LokNayak Navigation"):
        gr.Markdown("## ⚖️ LokNayak AI")
        new_chat_btn = gr.Button("➕ New Case Chat", elem_classes="new-chat-btn")
        gr.Markdown("---")
        gr.Markdown("### ⚙️ Engine Mode")
        pipeline_selector = gr.Radio(choices=["Fast Mode (Single AI)", "Multi-Agent Pipeline (Deep)"], value="Multi-Agent Pipeline (Deep)", label="", container=False)
        gr.Markdown("---")
        gr.Markdown("### 📜 Recent Conversations")
        history_dropdown = gr.Dropdown(label="Select Past Chat to Load", choices=[], value=None, interactive=True)
        gr.Markdown("---")
        gr.Markdown("### 👤 Account & Access")
        
        # Authentic Google Login Buttons mapped to FastAPI routes
        login_btn = gr.Button("🌐 Sign in with Google", variant="primary", link="/login")
        profile_html = gr.HTML("")
        logout_btn = gr.Button("Log Out", variant="secondary", link="/logout", visible=False)

    gr.HTML("<div class='header-bar'><h1>LokNayak Legal AI Assistant</h1><p style='color:#8e918f; font-size:0.85rem;'>Autonomous Multi-Agent Legal Research, Contract Review & Drafting</p></div>")
    chatbot = gr.Chatbot(label="", height=580, show_label=False, avatar_images=(None, "🏛️"))
    
    with gr.Row():
        file_input = gr.File(label="", file_types=[".pdf", ".docx"], type="filepath", scale=1, container=False)
        msg_input = gr.Textbox(placeholder="Ask a legal question or attach a PDF/DOCX contract...", show_label=False, container=False, scale=8)
        send_btn = gr.Button("Send", variant="primary", scale=1)

    status_text = gr.HTML("<div style='text-align:center; font-size:0.75rem; color:#8e918f; margin-top:8px;'>LokNayak AI outputs must be reviewed by a qualified attorney.</div>")

    # Dynamic Profile loader checks if FastAPI session has user data
    def load_user_profile(request: gr.Request):
        user = request.request.session.get('user') if request else None
        if user:
            name, email, pic = user.get('name', 'Counsel'), user.get('email', ''), user.get('picture', '')
            html = f"<div class='profile-card'><div style='display:flex; align-items:center; gap:10px;'><img src='{pic}' style='width:40px; height:40px; border-radius:50%;'><div><div style='font-weight:600; font-size:0.9rem; color:#e3e3e3;'>{name}</div><div style='font-size:0.75rem; color:#a8c7fa;'>{email}</div></div></div></div>"
            return gr.update(visible=False), html, gr.update(visible=True)
        return gr.update(visible=True), "", gr.update(visible=False)

    demo.load(fn=load_user_profile, inputs=None, outputs=[login_btn, profile_html, logout_btn])

    msg_input.submit(fn=process_chat, inputs=[msg_input, file_input, pipeline_selector, chatbot, chats_store, active_title], outputs=[msg_input, chatbot, chats_store, history_dropdown, status_text])
    send_btn.click(fn=process_chat, inputs=[msg_input, file_input, pipeline_selector, chatbot, chats_store, active_title], outputs=[msg_input, chatbot, chats_store, history_dropdown, status_text])
    history_dropdown.change(fn=load_past_chat, inputs=[history_dropdown, chats_store], outputs=[chatbot, active_title, status_text])
    new_chat_btn.click(fn=start_new_chat, inputs=[], outputs=[chatbot, file_input, active_title, history_dropdown, status_text])

# ═══════════════════════════════════════════════════════════════════
# 4. STARTUP HANDLER (MERGING FASTAPI & GRADIO)
# ═══════════════════════════════════════════════════════════════════
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
