# ═══════════════════════════════════════════════════════════════════
#  ⚖️ LOKNAYAK LEGAL AI — CHATGPT / GEMINI STYLE UI
#  Primary: Groq (Llama-3.3-70B) | Backup: Gemini Flash
# ═══════════════════════════════════════════════════════════════════

import gradio as gr
import requests
import time
import os
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
# Pulling keys directly from Render Environment Variables
GROQ_KEY = os.environ.get("GROQ_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

WORKING_PROVIDERS = []
if GROQ_KEY: WORKING_PROVIDERS.append("groq")
if GEMINI_KEY: WORKING_PROVIDERS.append("gemini")

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

# ─── CHAT LOGIC ───
def chat_response(user_message, file_obj, history):
    if not user_message.strip() and not file_obj:
        return "", history, "⚠️ Please type a query or attach a document."

    # Parse attached file
    doc_text = parse_file(file_obj) if file_obj else ""
    if len(doc_text) > 25000:
        doc_text = doc_text[:25000]

    # Append user turn to history
    display_msg = user_message
    if file_obj:
        filename = os.path.basename(file_obj)
        display_msg = f"📎 *[Attached: {filename}]*\n\n" + user_message

    history.append({"role": "user", "content": display_msg})
    yield "", history, "Thinking..."

    start_time = time.time()

    system_prompt = """You are LokNayak, an elite senior legal counsel AI.

CRITICAL FORMATTING REQUIREMENT:
Structure every legal response clearly using Markdown with these headings:
### 1. ISSUE
Concise legal framing of the question or subject matter.

### 2. ANALYSIS
Thorough, multi-perspective breakdown citing laws, principles, or contract provisions.

### 3. RECOMMENDATION
Actionable legal guidance or tactical next steps.

INSTRUCTIONS:
- Never provide brief or shallow answers.
- Maintain a formal, authoritative, professional legal tone.
- If a document is attached, base your analysis on its contents.
- Always end with: 'This is an AI-assisted analysis. Please review with a licensed attorney before use.'
"""

    full_query = user_message
    if doc_text:
        full_query += f"\n\n## ATTACHED DOCUMENT CONTEXT:\n{doc_text}"

    result = None
    provider_used = ""
    groq_err, gemini_err = "Not used", "Not used"

    # 1. GROQ (PRIMARY)
    if GROQ_KEY:
        try:
            messages = [{"role": "system", "content": system_prompt}]
            for msg in history[:-1]:
                role_map = "user" if msg["role"] == "user" else "assistant"
                messages.append({"role": role_map, "content": msg["content"]})
            messages.append({"role": "user", "content": full_query})

            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 2500
                },
                timeout=45
            )
            data = resp.json()
            if "choices" in data:
                result = data["choices"][0]["message"]["content"]
                provider_used = "Groq (Llama-3.3-70B)"
            else:
                groq_err = data.get('error', {}).get('message', 'API Error')
        except Exception as e:
            groq_err = str(e)

    # 2. GEMINI (BACKUP)
    if not result and GEMINI_KEY:
        try:
            client = genai.Client(api_key=GEMINI_KEY)
            contents = []
            for msg in history[:-1]:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=full_query)]))

            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=2500
                )
            )
            result = response.text
            provider_used = "Gemini (Flash-Latest)"
        except Exception as e:
            gemini_err = str(e)

    elapsed = round(time.time() - start_time, 1)

    if not result:
        err_output = f"❌ **Pipeline Failure**\n\n*Groq:* `{groq_err}`\n\n*Gemini:* `{gemini_err}`"
        history.append({"role": "assistant", "content": err_output})
        yield "", history, f"Failed in {elapsed}s"
        return

    history.append({"role": "assistant", "content": result})
    status = f"⚡ Answered in {elapsed}s via {provider_used}"
    yield "", history, status

# ─── GEMINI / CHATGPT STYLE CSS ───
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
.gradio-container {
    max-width: 950px !important;
    margin: 0 auto !important;
    padding: 10px !important;
}
.header-bar {
    text-align: center;
    padding: 20px 0 10px 0;
}
.header-bar h1 {
    font-size: 2rem;
    font-weight: 600;
    background: linear-gradient(135deg, #a8c7fa, #d3e3fd);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
}
.header-bar p {
    color: var(--text-muted);
    font-size: 0.9rem;
    margin-top: 4px;
}
footer { display: none !important; }
"""

# ─── UI LAYOUT ───
with gr.Blocks(title="LokNayak Legal AI") as demo:
    gr.HTML("""
        <div class="header-bar">
            <h1>⚖️ LokNayak Legal AI</h1>
            <p>Intelligent Legal Research, Analysis & Document Drafting</p>
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
            placeholder="Ask a legal question or request document analysis...",
            show_label=False,
            container=False,
            scale=8
        )
        send_btn = gr.Button("Send", variant="primary", scale=1)

    status_text = gr.HTML(
        "<div style='text-align:center; font-size:0.75rem; color:#8e918f; margin-top:8px;'>"
        "LokNayak AI outputs must be reviewed by a qualified attorney.</div>"
    )

    # Event Handlers
    msg_input.submit(
        fn=chat_response,
        inputs=[msg_input, file_input, chatbot],
        outputs=[msg_input, chatbot, status_text]
    )
    send_btn.click(
        fn=chat_response,
        inputs=[msg_input, file_input, chatbot],
        outputs=[msg_input, chatbot, status_text]
    )

demo.launch(server_name="0.0.0.0", server_port=10000, auth=list(USERS.items()), auth_message="Welcome to LokNayak Legal AI.", css=custom_css)
