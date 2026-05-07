from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>NanoClaw Runtime</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d8dee4;
      --text: #182026;
      --muted: #68737d;
      --accent: #0f766e;
      --accent-strong: #115e59;
      --agent: #eef6f5;
      --user: #17212b;
      --error: #b42318;
      --code: #f0f3f5;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }

    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
    }

    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }

    .bar {
      max-width: 1180px;
      margin: 0 auto;
      padding: 14px 20px;
      display: grid;
      grid-template-columns: minmax(180px, 1fr) auto;
      gap: 16px;
      align-items: center;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .mark {
      width: 34px;
      height: 34px;
      border: 1px solid var(--line);
      display: grid;
      place-items: center;
      font-weight: 800;
      color: var(--accent);
      background: #f8fbfb;
      border-radius: 6px;
      flex: none;
    }

    h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
      font-weight: 700;
    }

    .meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .status {
      display: flex;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 13px;
    }

    .dot {
      width: 9px;
      height: 9px;
      background: var(--accent);
      border-radius: 50%;
    }

    main {
      max-width: 1180px;
      width: 100%;
      margin: 0 auto;
      padding: 18px 20px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 18px;
      min-height: 0;
    }

    .chat, .side {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 0;
    }

    .chat {
      display: grid;
      grid-template-rows: 1fr auto;
      min-height: calc(100vh - 154px);
    }

    .messages {
      overflow: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .empty {
      height: 100%;
      min-height: 360px;
      display: grid;
      place-items: center;
      color: var(--muted);
      text-align: center;
      font-size: 14px;
    }

    .message {
      max-width: min(760px, 88%);
      padding: 12px 14px;
      border-radius: 8px;
      line-height: 1.55;
      font-size: 15px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .message.user {
      align-self: flex-end;
      color: #fff;
      background: var(--user);
    }

    .message.agent {
      align-self: flex-start;
      background: var(--agent);
      border: 1px solid #d8e9e6;
    }

    .message.system {
      align-self: center;
      max-width: 100%;
      color: var(--muted);
      background: var(--code);
      font-size: 13px;
    }

    form.composer {
      border-top: 1px solid var(--line);
      padding: 14px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
    }

    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      color: var(--text);
      background: #fff;
      resize: vertical;
    }

    textarea {
      min-height: 46px;
      max-height: 180px;
      line-height: 1.45;
    }

    button {
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 0 14px;
      min-height: 42px;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
    }

    button:hover { background: var(--accent-strong); }
    button:disabled { cursor: not-allowed; opacity: 0.55; }

    .secondary {
      width: 100%;
      background: #fff;
      color: var(--text);
      border-color: var(--line);
    }

    .secondary:hover { background: #f7f9fa; }

    .side {
      padding: 16px;
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 16px;
      align-content: start;
    }

    .field label, .events-title {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: 7px;
    }

    .row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }

    .events {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      min-height: 260px;
      background: #fbfcfd;
    }

    .event {
      padding: 10px;
      border-bottom: 1px solid var(--line);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      color: #33404a;
      word-break: break-word;
    }

    .event:last-child { border-bottom: 0; }
    .error { color: var(--error); }

    @media (max-width: 880px) {
      .bar, main {
        grid-template-columns: 1fr;
      }

      .status {
        justify-content: flex-start;
      }

      main {
        padding: 12px;
      }

      .chat {
        min-height: 62vh;
      }

      .message {
        max-width: 96%;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="bar">
        <div class="brand">
          <div class="mark">N</div>
          <div>
            <h1>NanoClaw Runtime</h1>
            <div class="meta" id="modelMeta">Connecting...</div>
          </div>
        </div>
        <div class="status"><span class="dot" id="statusDot"></span><span id="statusText">Checking health</span></div>
      </div>
    </header>

    <main>
      <section class="chat" aria-label="Chat">
        <div class="messages" id="messages">
          <div class="empty" id="empty">Start a session and send a text message.</div>
        </div>
        <form class="composer" id="composer">
          <textarea id="content" placeholder="Message NanoClaw" autocomplete="off"></textarea>
          <button id="send" type="submit">Send</button>
        </form>
      </section>

      <aside class="side" aria-label="Session tools">
        <div class="field">
          <label for="threadId">Thread ID</label>
          <div class="row">
            <input id="threadId" autocomplete="off" />
            <button class="secondary" id="newSession" type="button">New</button>
          </div>
        </div>
        <button class="secondary" id="refreshEvents" type="button">Refresh events</button>
        <div>
          <div class="events-title">Audit events</div>
          <div class="events" id="events"></div>
        </div>
      </aside>
    </main>
  </div>

  <script>
    const state = { busy: false };
    const messages = document.getElementById("messages");
    const empty = document.getElementById("empty");
    const content = document.getElementById("content");
    const send = document.getElementById("send");
    const threadId = document.getElementById("threadId");
    const eventsBox = document.getElementById("events");
    const statusText = document.getElementById("statusText");
    const modelMeta = document.getElementById("modelMeta");
    const statusDot = document.getElementById("statusDot");

    function setBusy(value) {
      state.busy = value;
      send.disabled = value;
      content.disabled = value;
    }

    function appendMessage(role, text) {
      empty.style.display = "none";
      const node = document.createElement("div");
      node.className = `message ${role}`;
      node.textContent = text;
      messages.appendChild(node);
      messages.scrollTop = messages.scrollHeight;
      return node;
    }

    async function checkHealth() {
      try {
        const response = await fetch("/health");
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "health check failed");
        statusText.textContent = "Online";
        modelMeta.textContent = `${data.provider} / ${data.model}`;
        statusDot.style.background = "var(--accent)";
      } catch (error) {
        statusText.textContent = "Offline";
        modelMeta.textContent = error.message;
        statusDot.style.background = "var(--error)";
      }
    }

    async function createSession() {
      const response = await fetch("/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "failed to create session");
      threadId.value = data.thread_id;
      eventsBox.innerHTML = "";
      appendMessage("system", `Session: ${data.thread_id}`);
    }

    async function refreshEvents() {
      if (!threadId.value.trim()) return;
      const response = await fetch(`/sessions/${encodeURIComponent(threadId.value.trim())}/events?limit=50`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "failed to load events");
      eventsBox.innerHTML = "";
      if (!data.events.length) {
        const item = document.createElement("div");
        item.className = "event";
        item.textContent = "No events yet.";
        eventsBox.appendChild(item);
        return;
      }
      for (const event of data.events) {
        const item = document.createElement("div");
        item.className = "event";
        item.textContent = JSON.stringify(event);
        eventsBox.appendChild(item);
      }
    }

    async function sendMessage(event) {
      event.preventDefault();
      const text = content.value.trim();
      if (!text || state.busy) return;
      if (!threadId.value.trim()) await createSession();

      appendMessage("user", text);
      content.value = "";
      setBusy(true);

      try {
        const response = await fetch(`/sessions/${encodeURIComponent(threadId.value.trim())}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: text })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "message failed");
        appendMessage("agent", data.content || "(empty response)");
        await refreshEvents();
      } catch (error) {
        appendMessage("system error", error.message);
      } finally {
        setBusy(false);
        content.focus();
      }
    }

    document.getElementById("composer").addEventListener("submit", sendMessage);
    document.getElementById("newSession").addEventListener("click", () => createSession().catch(error => appendMessage("system error", error.message)));
    document.getElementById("refreshEvents").addEventListener("click", () => refreshEvents().catch(error => appendMessage("system error", error.message)));
    content.addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        document.getElementById("composer").requestSubmit();
      }
    });

    checkHealth();
    createSession().catch(error => appendMessage("system error", error.message));
  </script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)

