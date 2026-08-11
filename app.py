# ═══════════════════════════════════════════════════════════════════
#  ⚖️ LOKNAYAK LEGAL AI — FINAL PRODUCTION DEPLOYMENT
#  Hybrid Multi-Agent Pipeline | Real Google OAuth | Gradio 6.0 Ready
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

# ─── CONFIG ───
APP_NAME = "LokNayak Legal AI"
USERS = {"admin": "loknayak2026", "lawyer1": "firm2026"}

print("=" * 60)
print(f"  🚀 STARTING {APP_NAME} SERVER")
print("=" * 60)

GROQ_KEY = os.environ.get("GROQ_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

# ─── FILE PARSER ───
def parse_file(file_path):
    if not file_path:
        return ""
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

# ─── OPTIMIZED MULTI-MODEL LLM HELPER ───
def call_llm(system_prompt, user_prompt, model_name="llama-3.1-8b-instant"):
    """
    Executes calls against Groq primary (with ultra-fast 8B for agents 1&2,
    and 70B for final synthesis) with fallback to Gemini.
    """
    if GROQ_KEY:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1800
                },
                timeout=20
            )
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"], f"Groq ({model_name})"
        except Exception:
            pass

    # Fallback to Gemini
    if GEMINI_KEY:
        try:
            client = genai.Client(api_key=GEMINI_KEY)
            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=2000
                )
            )
            return response.text, "Gemini Flash"
        except Exception:
            pass

    return None, "None"

# ─── MAIN CHAT CONTROLLER ───
def process_chat(user_message, file_obj, pipeline_mode, history, chats_store, current_title):
    if not user_message.strip() and not file_obj:
        yield "", history, chats_store, gr.update(), "⚠️ Please type a query or attach a document."
        return

    doc_text = parse_file(file_obj) if file_obj else ""
    if len(doc_text) > 20000:
        doc_text = doc_text[:20000]

    display_msg = user_message
    if file_obj:
        filename = os.path.basename(file_obj)
        display_msg = f"📎 *[Attached: {filename}]*\n\n" + user_message

    history.append({"role": "user", "content": display_msg})

    # Determine Title for Session History
    if not current_title or current_title == "New Case":
        active_title = user_message[:30] + "..." if len(user_message) > 30 else (user_message or "Doc Analysis")
    else:
        active_title = current_title

    start_time = time.time()
    input_payload = f"USER QUERY:\n{user_message}\n"
    if doc_text:
        input_payload += f"\nATTACHED DOCUMENT CONTEXT:\n{doc_text}\n"

    # ─────────────────────────────────────────────────────────────
    # MULTI-AGENT PIPELINE (HYBRID FAST ENGINE)
    # ─────────────────────────────────────────────────────────────
    if pipeline_mode == "Multi-Agent Pipeline (Deep)":
        history.append({"role": "assistant", "content": "🤖 **LokNayak Multi-Agent Pipeline Initiated...**\n\n"})
        yield "", history, chats_store, gr.update(), "Initiating Pipeline..."

        # Agent 1: Fast Research (llama-3.1-8b-instant)
        history[-1]["content"] += "🔍 **Agent 1 (Research):** Extracting relevant statutes & principles...\n"
        yield "", history, chats_store, gr.update(), "Agent 1 Working..."
        
        researcher_sys = "You are Agent 1: Legal Researcher. Extract core legal issues, Indian statutes, and applicable precedents."
        research_out, p1 = call_llm(researcher_sys, input_payload, model_name="llama-3.1-8b-instant")
        
        if not research_out:
            history[-1]["content"] += "\n❌ Pipeline Error: Engine unavailable."
            yield "", history, chats_store, gr.update(), "Failed"
            return
            
        history[-1]["content"] += f"✓ Research completed ({p1}).\n\n"
        yield "", history, chats_store, gr.update(), "Agent 2 Working..."

        # Agent 2: Risk Analysis (llama-3.1-8b-instant)
        history[-1]["content"] += "⚖️ **Agent 2 (Risk Analyst):** Evaluating liabilities and procedural weaknesses...\n"
        risk_sys = "You are Agent 2: Risk Analyst. Identify legal risks, evidentiary hurdles, and procedural weaknesses."
        risk_out, _ = call_llm(risk_sys, f"QUERY:\n{input_payload}\nRESEARCH:\n{research_out}", model_name="llama-3.1-8b-instant")
        
        history[-1]["content"] += "✓ Risk assessment completed.\n\n"
        yield "", history, chats_store, gr.update(), "Agent 3 Synthesizing..."

        # Agent 3: Senior Synthesis (llama-3.3-70b-versatile)
        history[-1]["content"] += "🏛️ **Agent 3 (Senior Counsel):** Finalizing legal analysis...\n\n---\n\n"
        synth_sys = """You are Agent 3: Senior Counsel. Synthesize findings into a final legal draft.
Structure using Markdown:
### 1. ISSUE
### 2. ANALYSIS
### 3. RECOMMENDATION
End with: 'This is an AI-assisted analysis generated by LokNayak. Please review with a licensed attorney before use.'"""

        final_out, _ = call_llm(synth_sys, f"CONTEXT:\n{input_payload}\nRESEARCH:\n{research_out}\nRISKS:\n{risk_out}", model_name="llama-3.3-70b-versatile")
        
        tokens = re.split(r'(\s+)', final_out or "Analysis failed.")
        for token in tokens:
            history[-1]["content"] += token
            yield "", history, chats_store, gr.update(), "Finalizing..."
            time.sleep(0.008)

    # ─────────────────────────────────────────────────────────────
    # SINGLE AGENT MODE (FAST)
    # ─────────────────────────────────────────────────────────────
    else:
        history.append({"role": "assistant", "content": ""})
        yield "", history, chats_store, gr.update(), "Thinking..."

        single_sys = """You are LokNayak, Senior Legal Counsel AI.
Structure every legal response using Markdown:
### 1. ISSUE
### 2. ANALYSIS
### 3. RECOMMENDATION
End with: 'This is an AI-assisted analysis. Please review with a licensed attorney before use.'"""

        res_text, provider = call_llm(single_sys, input_payload, model_name="llama-3.3-70b-versatile")
        tokens = re.split(r'(\s+)', res_text or "Analysis failed.")
        for token in tokens:
            history[-1]["content"] += token
            yield "", history, chats_store, gr.update(), "Typing..."
            time.sleep(0.01)

    # Save to Chat Store
    chats_store[active_title] = list(history)
    chat_choices = list(chats_store.keys())

    elapsed = round(time.time() - start_time, 1)
    yield "", history, chats_store, gr.update(choices=chat_choices, value=active_title), f"⚡ Processed in {elapsed}s"

# ─── RESTORE PAST CHAT FUNCTION ───
def load_past_chat(selected_title, chats_store):
    if selected_title in chats_store:
        return chats_store[selected_title], selected_title, f"Loaded past chat: {selected_title}"
    return [], "", "Ready"

# ─── NEW CHAT FUNCTION ───
def start_new_chat():
    return [], None, "", gr.update(value=None), "Started new chat session."

# ─── STYLING ───
custom_css = """
:root {
    --bg-main: #131314;
    --card-bg: #1e1f20;
    --text-primary: #e3e3e3;
    --text-muted: #8e918f;
    --accent: #a8c7fa;
}
body, .gradio-container {
    background-color: var(--bg-main) !important;
    color: var(--text-primary) !important;
    font-family: 'Google Sans', 'Inter', sans-serif !important;
}
.gradio-container { max-width: 1200px !important; margin: 0 auto !important; }
.header-bar { text-align: center; padding: 15px 0 5px 0; }
.header-bar h1 {
    font-size: 1.8rem; font-weight: 600;
    background: linear-gradient(135deg, #a8c7fa, #d3e3fd);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0;
}
.new-chat-btn button {
    background: #2b2c2e !important; color: #a8c7fa !important;
    border: 1px solid #3c4043 !important; border-radius: 20px !important; font-weight: 600 !important;
}
.profile-card {
    background: #2b2c2e; border-radius: 12px; padding: 12px; margin-top: 20px; border: 1px solid #3c4043;
}
footer { display: none !important; }
"""

# ─── UI LAYOUT ───
with gr.Blocks(title="LokNayak Legal AI") as demo:
    chats_store = gr.State({})
    active_title = gr.State("")

    # SIDEBAR
    with gr.Sidebar(label="LokNayak Navigation"):
        gr.Markdown("## ⚖️ LokNayak AI")
        
        new_chat_btn = gr.Button("➕ New Case Chat", elem_classes="new-chat-btn")
        
        gr.Markdown("---")
        
        gr.Markdown("### ⚙️ Engine Mode")
        pipeline_selector = gr.Radio(
            choices=["Fast Mode (Single AI)", "Multi-Agent Pipeline (Deep)"],
            value="Multi-Agent Pipeline (Deep)",
            label="",
            container=False
        )

        gr.Markdown("---")

        # CLICKABLE RECENT CHAT HISTORY
        gr.Markdown("### 📜 Recent Conversations")
        history_dropdown = gr.Dropdown(
            label="Select Past Chat to Load",
            choices=[],
            value=None,
            interactive=True
        )

        gr.Markdown("---")

        # REAL GOOGLE LOGIN BUTTON IS HERE
        gr.Markdown("### 👤 Account & Access")
        google_login_btn = gr.LoginButton() 
        
        gr.HTML("""
            <div class="profile-card">
                <div style="display:flex; align-items:center; gap:10px;">
                    <div style="font-size:1.5rem;">⚖️</div>
                    <div>
                        <div style="font-weight:600; font-size:0.9rem; color:#e3e3e3;">Authenticated Counsel</div>
                        <div style="font-size:0.75rem; color:#8e918f;">Active Workspace: Enterprise</div>
                    </div>
                </div>
            </div>
        """)

    # MAIN CHAT
    gr.HTML("""
        <div class="header-bar">
            <h1>LokNayak Legal AI Assistant</h1>
            <p style="color:#8e918f; font-size:0.85rem;">Autonomous Multi-Agent Legal Research, Contract Review & Drafting</p>
        </div>
    """)

    chatbot = gr.Chatbot(
        label="",
        height=580,
        show_label=False,
        avatar_images=(None, "🏛️")
    )

    with gr.Row():
        file_input = gr.File(
            label="",
            file_types=[".pdf", ".docx"],
            type="filepath",
            scale=1,
            container=False
        )
        msg_input = gr.Textbox(
            placeholder="Ask a legal question or attach a PDF/DOCX contract...",
            show_label=False,
            container=False,
            scale=8
        )
        send_btn = gr.Button("Send", variant="primary", scale=1)

    status_text = gr.HTML(
        "<div style='text-align:center; font-size:0.75rem; color:#8e918f; margin-top:8px;'>"
        "LokNayak AI outputs must be reviewed by a qualified attorney.</div>"
    )

    # ─── EVENT BINDINGS ───
    
    # Send Message
    msg_input.submit(
        fn=process_chat,
        inputs=[msg_input, file_input, pipeline_selector, chatbot, chats_store, active_title],
        outputs=[msg_input, chatbot, chats_store, history_dropdown, status_text]
    )

    send_btn.click(
        fn=process_chat,
        inputs=[msg_input, file_input, pipeline_selector, chatbot, chats_store, active_title],
        outputs=[msg_input, chatbot, chats_store, history_dropdown, status_text]
    )

    # Select and Load Past Chat from Sidebar Dropdown
    history_dropdown.change(
        fn=load_past_chat,
        inputs=[history_dropdown, chats_store],
        outputs=[chatbot, active_title, status_text]
    )

    # New Chat Button
    new_chat_btn.click(
        fn=start_new_chat,
        inputs=[],
        outputs=[chatbot, file_input, active_title, history_dropdown, status_text]
    )

PORT = int(os.environ.get("PORT", 10000))
demo.launch(server_name="0.0.0.0", server_port=PORT, css=custom_css)
