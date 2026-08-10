# ═══════════════════════════════════════════════════════════════════
#  ⚖️ LOKNAYAK LEGAL AI — FULL FEATURE SIDEBAR & MULTI-AGENT PLATFORM
#  Features: Sidebar, Google Auth UI, New Chat, History, Multi-Agent Toggle
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

# ─── LLM ENGINE HELPER ───
def call_llm(system_prompt, user_prompt):
    """Executes calls against Groq primary or Gemini backup."""
    # 1. Groq Call
    if GROQ_KEY:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 2000
                },
                timeout=35
            )
            data = resp.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"], "Groq Llama-3.3"
        except Exception:
            pass

    # 2. Gemini Backup Call
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

# ─── CHAT CONTROLLER (Single vs Multi-Agent) ───
def process_chat(user_message, file_obj, pipeline_mode, history, session_list):
    if not user_message.strip() and not file_obj:
        yield "", history, session_list, "⚠️ Please type a query or attach a document."
        return

    doc_text = parse_file(file_obj) if file_obj else ""
    if len(doc_text) > 20000:
        doc_text = doc_text[:20000]

    display_msg = user_message
    if file_obj:
        filename = os.path.basename(file_obj)
        display_msg = f"📎 *[Attached: {filename}]*\n\n" + user_message

    history.append({"role": "user", "content": display_msg})
    
    # Update Session History List
    short_title = user_message[:28] + "..." if len(user_message) > 28 else (user_message or "Document Review")
    if short_title not in session_list:
        session_list.insert(0, short_title)

    start_time = time.time()
    input_payload = f"USER QUERY:\n{user_message}\n"
    if doc_text:
        input_payload += f"\nATTACHED DOCUMENT CONTEXT:\n{doc_text}\n"

    # ─────────────────────────────────────────────────────────────
    # MODE 1: MULTI-AGENT COLLABORATIVE PIPELINE
    # ─────────────────────────────────────────────────────────────
    if pipeline_mode == "Multi-Agent Pipeline (Deep)":
        history.append({"role": "assistant", "content": "🤖 **LokNayak Multi-Agent Pipeline Initiated...**\n\n"})
        yield "", history, session_list, "Initiating Multi-Agent Pipeline..."

        # Step 1: Legal Researcher
        history[-1]["content"] += "🔍 **Agent 1 (Legal Researcher):** Scanning statutes, cases, and constitutional provisions...\n"
        yield "", history, session_list, "Agent 1 Working..."
        
        researcher_sys = "You are Agent 1: Senior Legal Researcher. Extract legal issues, statutes, and applicable precedents."
        research_out, provider = call_llm(researcher_sys, input_payload)
        
        if not research_out:
            history[-1]["content"] += "\n❌ Pipeline Error: Providers failed."
            yield "", history, session_list, "Failed"
            return
            
        history[-1]["content"] += f"✓ Research complete ({provider}).\n\n"
        yield "", history, session_list, "Agent 2 Working..."

        # Step 2: Risk Analyst
        history[-1]["content"] += "⚖️ **Agent 2 (Risk Analyst):** Evaluating procedural defenses and liabilities...\n"
        risk_sys = "You are Agent 2: Legal Risk Analyst. Identify liabilities, loopholes, procedural weaknesses, and risks."
        risk_out, _ = call_llm(risk_sys, f"QUERY:\n{input_payload}\nRESEARCH:\n{research_out}")
        
        history[-1]["content"] += "✓ Risk assessment complete.\n\n"
        yield "", history, session_list, "Agent 3 Synthesizing..."

        # Step 3: Senior Counsel Synthesizer
        history[-1]["content"] += "🏛️ **Agent 3 (Senior Counsel):** Drafting final legal analysis...\n\n---\n\n"
        synth_sys = """You are Agent 3: Senior Legal Counsel. Synthesize all findings into a structured legal response.
Formatting:
### 1. ISSUE
### 2. ANALYSIS
### 3. RECOMMENDATION
End with: 'This is an AI-assisted analysis generated by LokNayak. Please review with a licensed attorney before use.'"""

        final_out, _ = call_llm(synth_sys, f"CONTEXT:\n{input_payload}\nRESEARCH:\n{research_out}\nRISKS:\n{risk_out}")
        
        tokens = re.split(r'(\s+)', final_out or "Analysis failed.")
        for token in tokens:
            history[-1]["content"] += token
            yield "", history, session_list, "Finalizing..."
            time.sleep(0.01)

    # ─────────────────────────────────────────────────────────────
    # MODE 2: SINGLE AGENT FAST MODE
    # ─────────────────────────────────────────────────────────────
    else:
        history.append({"role": "assistant", "content": ""})
        yield "", history, session_list, "Thinking..."

        single_sys = """You are LokNayak, an elite senior legal counsel AI.
Structure every legal response clearly using Markdown:
### 1. ISSUE
### 2. ANALYSIS
### 3. RECOMMENDATION
End with: 'This is an AI-assisted analysis. Please review with a licensed attorney before use.'"""

        res_text, provider = call_llm(single_sys, input_payload)
        tokens = re.split(r'(\s+)', res_text or "Analysis failed.")
        for token in tokens:
            history[-1]["content"] += token
            yield "", history, session_list, "Typing..."
            time.sleep(0.012)

    elapsed = round(time.time() - start_time, 1)
    yield "", history, session_list, f"⚡ Processed in {elapsed}s"

# ─── NEW CHAT RESET FUNCTION ───
def start_new_chat():
    return [], None, "Started new chat session."

# ─── STYLING & CUSTOM CSS ───
custom_css = """
:root {
    --bg-main: #131314;
    --card-bg: #1e1f20;
    --text-primary: #e3e3e3;
    --text-muted: #8e918f;
    --accent: #a8c7fa;
    --sidebar-bg: #1e1f20;
}
body, .gradio-container {
    background-color: var(--bg-main) !important;
    color: var(--text-primary) !important;
    font-family: 'Google Sans', 'Inter', sans-serif !important;
}
.gradio-container {
    max-width: 1200px !important;
    margin: 0 auto !important;
}
.header-bar {
    text-align: center;
    padding: 15px 0 5px 0;
}
.header-bar h1 {
    font-size: 1.8rem;
    font-weight: 600;
    background: linear-gradient(135deg, #a8c7fa, #d3e3fd);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
}
.new-chat-btn button {
    background: #2b2c2e !important;
    color: #a8c7fa !important;
    border: 1px solid #3c4043 !important;
    border-radius: 20px !important;
    font-weight: 600 !important;
}
.profile-card {
    background: #2b2c2e;
    border-radius: 12px;
    padding: 12px;
    margin-top: 20px;
    border: 1px solid #3c4043;
}
footer { display: none !important; }
"""

# ─── UI LAYOUT WITH SIDEBAR ───
with gr.Blocks(title="LokNayak Legal AI", css=custom_css) as demo:
    session_state = gr.State([])

    # ─────────────────────────────────────────────────────────────
    # SIDEBAR PANEL (ChatGPT / Gemini Style)
    # ─────────────────────────────────────────────────────────────
    with gr.Sidebar(label="LokNayak Navigation"):
        gr.Markdown("## ⚖️ LokNayak AI")
        
        # 1. New Chat Button
        new_chat_btn = gr.Button("➕ New Case Chat", elem_classes="new-chat-btn")
        
        gr.Markdown("---")
        
        # 2. Pipeline Mode Switch
        gr.Markdown("### ⚙️ Engine Mode")
        pipeline_selector = gr.Radio(
            choices=["Fast Mode (Single AI)", "Multi-Agent Pipeline (Deep)"],
            value="Multi-Agent Pipeline (Deep)",
            label="",
            container=False
        )

        gr.Markdown("---")

        # 3. Recent Case Sessions
        gr.Markdown("### 🕒 Recent Sessions")
        session_display = gr.Markdown("No active cases in this session.")

        gr.Markdown("---")

        # 4. Google Auth & User Profile Section
        gr.Markdown("### 👤 Account & Access")
        # Native Gradio Google OAuth Component
        google_auth_btn = gr.OAuthButton()
        
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

    # ─────────────────────────────────────────────────────────────
    # MAIN CHAT PANEL
    # ─────────────────────────────────────────────────────────────
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
        show_copy_button=True,
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

    # ─── EVENT HANDLERS ───
    
    # Session list display formatter
    def update_session_ui(sessions):
        if not sessions:
            return "No active cases."
        return "\n".join([f"• {s}" for s in sessions[:5]])

    # Chat Submit Handlers
    chat_event = msg_input.submit(
        fn=process_chat,
        inputs=[msg_input, file_input, pipeline_selector, chatbot, session_state],
        outputs=[msg_input, chatbot, session_state, status_text]
    ).then(
        fn=update_session_ui,
        inputs=session_state,
        outputs=session_display
    )

    send_btn.click(
        fn=process_chat,
        inputs=[msg_input, file_input, pipeline_selector, chatbot, session_state],
        outputs=[msg_input, chatbot, session_state, status_text]
    ).then(
        fn=update_session_ui,
        inputs=session_state,
        outputs=session_display
    )

    # New Chat Handler
    new_chat_btn.click(
        fn=start_new_chat,
        inputs=[],
        outputs=[chatbot, file_input, status_text]
    )

PORT = int(os.environ.get("PORT", 10000))
demo.launch(server_name="0.0.0.0", server_port=PORT, auth=list(USERS.items()), auth_message="Welcome to LokNayak Legal AI Platform.", css=custom_css)
