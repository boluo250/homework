INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>TaskMate Worker Demo</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="page-shell">
      <aside class="sidebar">
        <div class="brand-card">
          <p class="eyebrow">Cloudflare Worker MVP</p>
          <h1>TaskMate</h1>
          <p class="brand-lead">把任务管理、研究模式和文件问答收进同一块清晰的工作台。</p>
          <p class="muted">一个面向面试作业的轻量任务、研究与文件问答助手。</p>
          <div class="brand-metrics">
            <div class="metric-chip">
              <span class="metric-label">Context</span>
              <strong>Shared</strong>
            </div>
            <div class="metric-chip">
              <span class="metric-label">Research</span>
              <strong>Ready</strong>
            </div>
            <div class="metric-chip">
              <span class="metric-label">Files</span>
              <strong>RAG</strong>
            </div>
          </div>
        </div>

        <section class="panel">
          <div class="panel-header">
            <h2>任务列表</h2>
            <button id="refreshTasksButton" class="ghost-button">刷新</button>
          </div>
          <p class="section-note">统一查看当前用户上下文下的待办、优先级和截止信息。</p>
          <div id="taskList" class="stack empty-state">还没有任务</div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>文件工作区</h2>
            <span class="badge">RAG Ready</span>
          </div>
          <p class="section-note">上传资料后，可以把选中的文件作为聊天上下文直接参与问答。</p>
          <form id="uploadForm" class="upload-form">
            <input id="fileInput" type="file" accept=".txt,.md,.pdf,.docx" />
            <button type="submit" class="ghost-button">上传文件</button>
          </form>
          <p id="uploadStatus" class="muted">支持 txt、md、pdf、docx、png、jpg、jpeg，单文件最大 10MB。</p>
          <div id="fileList" class="stack empty-state">还没有文件</div>
        </section>
      </aside>

      <main class="main-column">
        <section class="hero">
          <div class="hero-copy">
            <p class="eyebrow">P0 Demo Ready</p>
            <h2>对话、任务、研究、文件问答都走同一套用户上下文</h2>
            <p class="hero-summary">更适合演示的工作流体验：一边聊，一边落任务、发起研究、引用文件，不需要来回切系统。</p>
          </div>
          <div class="hero-actions">
            <span id="clientIdTag" class="badge"></span>
            <button id="newConversationButton" class="ghost-button">新会话</button>
            <button id="resetDataButton" class="inline-danger">清空数据</button>
          </div>
        </section>

        <section class="chat-panel">
          <div id="messageList" class="message-list"></div>

          <form id="chatForm" class="composer">
            <textarea
              id="messageInput"
              name="message"
              rows="3"
              placeholder="试试：帮我创建一个“简历优化”任务，下周五前完成，高优先级"
            ></textarea>
            <div class="composer-footer">
              <p id="selectedFilesHint" class="muted">当前没有选中的文件上下文</p>
              <button type="submit" class="primary-button">发送</button>
            </div>
          </form>
        </section>

        <section class="panel report-panel">
          <div class="panel-header">
            <h2>研究结果区</h2>
            <span id="researchStatusTag" class="badge">idle</span>
          </div>
          <pre id="reportBox" class="report-box">等待研究模式返回结果...</pre>
        </section>
      </main>
    </div>

    <template id="messageTemplate">
      <article class="message">
        <div class="message-meta"></div>
        <div class="message-body"></div>
      </article>
    </template>

    <script src="/app.js" defer></script>
  </body>
</html>
"""

STYLES_CSS = """:root {
  --bg-top: #f6efe6;
  --bg-bottom: #f1f5ef;
  --paper: rgba(255, 251, 247, 0.82);
  --paper-strong: #fffdf9;
  --paper-soft: rgba(255, 255, 255, 0.58);
  --ink: #182126;
  --muted: #61707a;
  --muted-strong: #485761;
  --accent: #c85b3d;
  --accent-strong: #a34228;
  --accent-soft: rgba(200, 91, 61, 0.12);
  --accent-glow: rgba(200, 91, 61, 0.22);
  --teal-soft: rgba(59, 124, 112, 0.14);
  --line: rgba(24, 33, 38, 0.1);
  --line-strong: rgba(24, 33, 38, 0.16);
  --shadow-lg: 0 32px 70px rgba(48, 43, 36, 0.14);
  --shadow-md: 0 16px 38px rgba(48, 43, 36, 0.1);
  --shadow-sm: 0 8px 18px rgba(48, 43, 36, 0.08);
}

* {
  box-sizing: border-box;
}

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--ink);
  font-family: "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", sans-serif;
  background:
    radial-gradient(circle at 0% 0%, rgba(200, 91, 61, 0.2), transparent 28%),
    radial-gradient(circle at 100% 20%, rgba(59, 124, 112, 0.18), transparent 26%),
    linear-gradient(145deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
}

body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.08) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.35), transparent 75%);
}

.page-shell {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 28px;
  max-width: 1480px;
  margin: 0 auto;
  padding: 28px;
}

.sidebar,
.main-column {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.brand-card,
.panel,
.chat-panel,
.hero {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 28px;
  background: var(--paper);
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(18px);
  overflow: hidden;
}

.brand-card::after,
.hero::after {
  content: "";
  position: absolute;
  inset: auto -40px -40px auto;
  width: 180px;
  height: 180px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.22), transparent 70%);
  pointer-events: none;
}

.brand-card,
.panel,
.hero {
  padding: 24px;
}

.panel {
  background: linear-gradient(180deg, rgba(255, 252, 247, 0.88), rgba(255, 255, 255, 0.72));
}

.chat-panel {
  display: flex;
  flex-direction: column;
  min-height: 680px;
}

.brand-card {
  background:
    radial-gradient(circle at top right, rgba(200, 91, 61, 0.18), transparent 34%),
    linear-gradient(145deg, rgba(255, 251, 248, 0.9), rgba(255, 246, 239, 0.76));
}

.brand-lead,
.hero-summary {
  max-width: 32rem;
  font-size: 15px;
  line-height: 1.75;
  color: var(--muted-strong);
}

.brand-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.metric-chip {
  padding: 14px 12px;
  border: 1px solid rgba(24, 33, 38, 0.08);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.metric-chip strong,
.metric-chip span {
  display: block;
}

.metric-label {
  margin-bottom: 6px;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}

.section-note {
  margin: 10px 0 16px;
  color: var(--muted);
  line-height: 1.6;
}

.eyebrow {
  margin: 0 0 12px;
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h1,
h2,
p,
pre {
  margin-top: 0;
}

h1 {
  margin-bottom: 12px;
  font-size: clamp(2.4rem, 4vw, 3.4rem);
  line-height: 0.98;
  letter-spacing: -0.04em;
}

h2 {
  margin-bottom: 0;
  font-size: clamp(1.4rem, 2.4vw, 2rem);
  line-height: 1.15;
  letter-spacing: -0.03em;
}

.muted {
  color: var(--muted);
  line-height: 1.7;
}

.panel-header,
.hero,
.composer-footer,
.task-topline,
.file-select,
.hero-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero {
  align-items: flex-start;
  background:
    radial-gradient(circle at top left, rgba(200, 91, 61, 0.16), transparent 28%),
    linear-gradient(135deg, rgba(255, 249, 243, 0.95), rgba(248, 252, 248, 0.82));
}

.hero-copy {
  max-width: 760px;
}

.hero-actions {
  flex-direction: column;
  align-items: flex-end;
  min-width: 180px;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.badge,
.type-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid rgba(200, 91, 61, 0.08);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.type-tag {
  border-color: rgba(24, 33, 38, 0.08);
  background: rgba(24, 33, 38, 0.06);
  color: var(--ink);
}

.primary-button,
.ghost-button,
.inline-danger {
  appearance: none;
  border-radius: 999px;
  padding: 11px 18px;
  border: 1px solid transparent;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  transition:
    transform 160ms ease,
    box-shadow 160ms ease,
    background 160ms ease,
    border-color 160ms ease,
    opacity 160ms ease;
}

.primary-button:hover,
.ghost-button:hover,
.inline-danger:hover {
  transform: translateY(-1px);
}

.primary-button {
  color: #fff;
  background: linear-gradient(135deg, var(--accent) 0%, #b84e32 100%);
  box-shadow: 0 14px 28px rgba(200, 91, 61, 0.26);
}

.primary-button:hover {
  box-shadow: 0 18px 36px rgba(200, 91, 61, 0.32);
}

.ghost-button {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.56);
  border-color: rgba(24, 33, 38, 0.08);
  box-shadow: var(--shadow-sm);
}

.ghost-button:hover {
  background: rgba(255, 255, 255, 0.82);
}

.inline-danger {
  padding: 9px 14px;
  color: var(--accent-strong);
  background: rgba(163, 66, 40, 0.08);
  border-color: rgba(163, 66, 40, 0.1);
}

.message-list {
  min-height: 460px;
  max-height: 60vh;
  overflow: auto;
  padding: 26px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.28), rgba(255, 255, 255, 0.08)),
    radial-gradient(circle at top left, rgba(59, 124, 112, 0.08), transparent 26%);
}

.message-list::-webkit-scrollbar,
.report-box::-webkit-scrollbar {
  width: 10px;
}

.message-list::-webkit-scrollbar-thumb,
.report-box::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(24, 33, 38, 0.16);
}

.message {
  max-width: min(82%, 760px);
  padding: 16px 18px;
  border-radius: 22px;
  background: var(--paper-strong);
  border: 1px solid rgba(24, 33, 38, 0.08);
  box-shadow: var(--shadow-sm);
}

.message[data-role="user"] {
  align-self: flex-end;
  background: linear-gradient(145deg, rgba(200, 91, 61, 0.14), rgba(200, 91, 61, 0.08));
  border-color: rgba(200, 91, 61, 0.16);
}

.message[data-role="assistant"] {
  align-self: flex-start;
}

.message-meta {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.message-body {
  white-space: pre-wrap;
  line-height: 1.72;
  color: var(--ink);
}

.composer {
  margin: 16px;
  padding: 18px;
  border-radius: 24px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.74), rgba(255, 253, 250, 0.66));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

textarea,
input[type="file"] {
  width: 100%;
  border-radius: 20px;
  border: 1px solid var(--line);
  padding: 16px 18px;
  background: rgba(255, 255, 255, 0.92);
  font: inherit;
  color: var(--ink);
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

textarea {
  min-height: 120px;
  resize: vertical;
  line-height: 1.7;
}

textarea:focus,
input[type="file"]:focus {
  outline: none;
  border-color: rgba(200, 91, 61, 0.34);
  box-shadow: 0 0 0 4px rgba(200, 91, 61, 0.1);
}

input[type="file"] {
  padding: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(252, 247, 241, 0.86));
}

input[type="file"]::file-selector-button {
  margin-right: 12px;
  padding: 10px 14px;
  border: 0;
  border-radius: 999px;
  background: rgba(24, 33, 38, 0.08);
  color: var(--ink);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.composer-footer {
  margin-top: 14px;
  align-items: flex-end;
}

.composer-footer .muted {
  margin-bottom: 0;
}

.report-panel {
  min-height: 280px;
}

.report-box {
  min-height: 240px;
  margin: 0;
  padding: 20px;
  border-radius: 22px;
  background:
    radial-gradient(circle at top right, rgba(200, 91, 61, 0.12), transparent 26%),
    linear-gradient(180deg, #1c2427 0%, #11181c 100%);
  color: #edf2ef;
  overflow: auto;
  white-space: pre-wrap;
  line-height: 1.72;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.task-card,
.file-card {
  padding: 16px;
  border-radius: 22px;
  background: var(--paper-soft);
  border: 1px solid rgba(24, 33, 38, 0.08);
  box-shadow: var(--shadow-sm);
}

.task-card {
  position: relative;
  overflow: hidden;
}

.task-card::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 5px;
  border-radius: 999px;
}

.priority-high::before {
  background: #c64327;
}

.priority-medium::before {
  background: #d79d2d;
}

.priority-low::before {
  background: #5b8f6a;
}

.file-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.file-select {
  flex: 1;
  align-items: flex-start;
  justify-content: flex-start;
  gap: 14px;
  min-width: 0;
}

.file-select input[type="checkbox"] {
  width: 18px;
  height: 18px;
  margin-top: 4px;
  accent-color: var(--accent);
}

.file-main {
  flex: 1;
  min-width: 0;
}

.task-topline strong,
.file-main strong {
  font-size: 15px;
  display: block;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.file-topline {
  margin-bottom: 10px;
}

.file-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.file-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: flex-start;
  gap: 10px;
  min-width: 112px;
}

.upload-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  margin-bottom: 12px;
}

.empty-state {
  justify-content: center;
  min-height: 108px;
  padding: 18px;
  border: 1px dashed rgba(24, 33, 38, 0.14);
  border-radius: 20px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.38);
}

@media (max-width: 1180px) {
  .page-shell {
    grid-template-columns: 1fr;
  }

  .hero {
    flex-direction: column;
  }

  .hero-actions {
    width: 100%;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

@media (max-width: 760px) {
  .page-shell {
    padding: 16px;
    gap: 18px;
  }

  .brand-card,
  .panel,
  .hero {
    padding: 18px;
  }

  .chat-panel {
    min-height: 560px;
  }

  .message-list {
    padding: 18px;
    max-height: none;
  }

  .message {
    max-width: 100%;
  }

  .brand-metrics,
  .upload-form {
    grid-template-columns: 1fr;
  }

  .composer {
    margin: 12px;
    padding: 14px;
  }

  .composer-footer,
  .file-card {
    flex-direction: column;
    align-items: stretch;
  }

  .file-select {
    width: 100%;
  }

  .hero-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
"""

APP_JS = """const storageKeys = {
  clientId: "taskmate-client-id",
  conversationId: "taskmate-conversation-id",
};

const state = {
  clientId: loadOrCreateClientId(),
  conversationId: localStorage.getItem(storageKeys.conversationId) || "",
  selectedFileIds: new Set(),
  researchJobId: "",
};

const dom = {
  chatForm: document.getElementById("chatForm"),
  messageInput: document.getElementById("messageInput"),
  messageList: document.getElementById("messageList"),
  taskList: document.getElementById("taskList"),
  fileList: document.getElementById("fileList"),
  reportBox: document.getElementById("reportBox"),
  refreshTasksButton: document.getElementById("refreshTasksButton"),
  newConversationButton: document.getElementById("newConversationButton"),
  resetDataButton: document.getElementById("resetDataButton"),
  clientIdTag: document.getElementById("clientIdTag"),
  messageTemplate: document.getElementById("messageTemplate"),
  uploadForm: document.getElementById("uploadForm"),
  fileInput: document.getElementById("fileInput"),
  uploadStatus: document.getElementById("uploadStatus"),
  researchStatusTag: document.getElementById("researchStatusTag"),
  selectedFilesHint: document.getElementById("selectedFilesHint"),
};

dom.clientIdTag.textContent = `client_id: ${state.clientId}`;
appendMessage("assistant", "你好，我已经准备好接住任务、普通对话、研究请求和文件问答了。");
refreshTasks();
refreshFiles();
renderSelectedFilesHint();

dom.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = dom.messageInput.value.trim();
  if (!message) return;

  appendMessage("user", message);
  dom.messageInput.value = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        client_id: state.clientId,
        conversation_id: state.conversationId || null,
        message,
        file_ids: Array.from(state.selectedFileIds),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Request failed");
    }

    state.conversationId = payload.conversation_id;
    localStorage.setItem(storageKeys.conversationId, state.conversationId);
    appendMessage("assistant", payload.reply);

    await refreshTasks(payload.user_profile?.id);
    await refreshFiles();

    if (payload.intent === "deep_research") {
      await submitResearchJob(message);
    }
  } catch (error) {
    appendMessage("assistant", `请求失败：${error.message}`);
  }
});

dom.refreshTasksButton.addEventListener("click", async () => {
  await refreshTasks();
});

dom.newConversationButton.addEventListener("click", () => {
  state.conversationId = "";
  localStorage.removeItem(storageKeys.conversationId);
  dom.messageList.innerHTML = "";
  appendMessage("assistant", "已经为你开启一个新会话。");
});

dom.resetDataButton.addEventListener("click", async () => {
  const confirmed = window.confirm("这会清空当前环境里的 D1、R2 和 Qdrant 数据，确定继续吗？");
  if (!confirmed) return;

  dom.uploadStatus.textContent = "正在清空 D1、R2 和 Qdrant 数据...";
  try {
    const response = await fetch("/api/admin/reset", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ confirm: "RESET_ALL_DATA" }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Reset failed");
    }
    state.selectedFileIds.clear();
    state.conversationId = "";
    state.researchJobId = "";
    localStorage.removeItem(storageKeys.conversationId);
    dom.messageList.innerHTML = "";
    appendMessage("assistant", "数据已经清空。现在可以重新上传文件并从干净状态开始测试。");
    dom.reportBox.textContent = "等待研究模式返回结果..."
    dom.researchStatusTag.textContent = "idle";
    dom.uploadStatus.textContent = `已清空数据，R2 删除 ${payload.deleted_r2_count} 个文件。`;
    await refreshTasks();
    await refreshFiles();
    renderSelectedFilesHint();
  } catch (error) {
    dom.uploadStatus.textContent = `清空失败：${error.message}`;
  }
});

dom.uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = dom.fileInput.files[0];
  if (!file) {
    dom.uploadStatus.textContent = "先选择一个文件再上传。";
    return;
  }

  dom.uploadStatus.textContent = `正在上传 ${file.name}...`;
  try {
    const contentBase64 = await readFileAsBase64(file);
    const response = await fetch("/api/files", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        client_id: state.clientId,
        filename: file.name,
        content_type: file.type || guessContentType(file.name),
        content_base64: contentBase64,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Upload failed");
    }
    dom.uploadStatus.textContent = `上传完成：${payload.file.filename}，共切分 ${payload.chunk_count} 个片段，Qdrant 已写入 ${payload.vector_count} 条向量。`;
    dom.fileInput.value = "";
    await refreshFiles(payload.user_id);
  } catch (error) {
    dom.uploadStatus.textContent = `上传失败：${error.message}`;
  }
});

async function refreshTasks(userId = "") {
  const resolvedUserId = userId || window.__taskmateLastUserId || "";
  const query = resolvedUserId
    ? `user_id=${encodeURIComponent(resolvedUserId)}`
    : `client_id=${encodeURIComponent(state.clientId)}`;

  const response = await fetch(`/api/tasks?${query}`);
  const payload = await response.json();
  window.__taskmateLastUserId = payload.user_id || resolvedUserId;
  dom.taskList.innerHTML = "";

  if (!payload.tasks || payload.tasks.length === 0) {
    dom.taskList.className = "stack empty-state";
    dom.taskList.textContent = "还没有任务";
    return;
  }

  dom.taskList.className = "stack";
  for (const task of payload.tasks) {
    const card = document.createElement("article");
    card.className = `task-card priority-${task.priority}`;
    card.innerHTML = `
      <div class="task-topline">
        <strong>${escapeHtml(task.title)}</strong>
        <span class="badge">${task.priority}</span>
      </div>
      <p class="muted">status: ${task.status}</p>
      <p class="muted">due: ${task.due_at || "n/a"}</p>
    `;
    dom.taskList.appendChild(card);
  }
}

async function refreshFiles(userId = "") {
  const resolvedUserId = userId || window.__taskmateLastUserId || "";
  const query = resolvedUserId
    ? `user_id=${encodeURIComponent(resolvedUserId)}`
    : `client_id=${encodeURIComponent(state.clientId)}`;
  const response = await fetch(`/api/files?${query}`);
  const payload = await response.json();
  dom.fileList.innerHTML = "";

  if (!payload.files || payload.files.length === 0) {
    dom.fileList.className = "stack empty-state";
    dom.fileList.textContent = "还没有文件";
    renderSelectedFilesHint();
    return;
  }

  dom.fileList.className = "stack";
  const validIds = new Set(payload.files.map((file) => file.id));
  for (const selectedId of Array.from(state.selectedFileIds)) {
    if (!validIds.has(selectedId)) {
      state.selectedFileIds.delete(selectedId);
    }
  }

  for (const file of payload.files) {
    const card = document.createElement("article");
    card.className = "file-card";
    card.innerHTML = `
      <label class="file-select">
        <input type="checkbox" ${state.selectedFileIds.has(file.id) ? "checked" : ""} data-file-id="${escapeHtml(file.id)}" />
        <div class="file-main">
          <div class="file-topline">
            <strong>${escapeHtml(file.filename)}</strong>
          </div>
        </div>
      </label>
      <div class="file-actions">
        <button class="inline-danger" type="button" data-delete-file-id="${escapeHtml(file.id)}">删除文件</button>
      </div>
    `;
    dom.fileList.appendChild(card);
  }

  dom.fileList.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    checkbox.addEventListener("change", (event) => {
      const fileId = event.target.dataset.fileId;
      if (event.target.checked) {
        state.selectedFileIds.add(fileId);
      } else {
        state.selectedFileIds.delete(fileId);
      }
      renderSelectedFilesHint();
    });
  });

  dom.fileList.querySelectorAll("[data-delete-file-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const fileId = button.dataset.deleteFileId;
      await deleteFile(fileId);
    });
  });

  renderSelectedFilesHint();
}

async function deleteFile(fileId) {
  const response = await fetch(
    `/api/files?client_id=${encodeURIComponent(state.clientId)}&file_id=${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );
  const payload = await response.json();
  if (!response.ok) {
    dom.uploadStatus.textContent = `删除失败：${payload.error || "Unknown error"}`;
    return;
  }
  state.selectedFileIds.delete(fileId);
  dom.uploadStatus.textContent = `已删除文件：${payload.deleted.filename}`;
  await refreshFiles();
}

async function submitResearchJob(query) {
  dom.researchStatusTag.textContent = "pending";
  dom.reportBox.textContent = "研究任务已提交，正在轮询结果...";
  const response = await fetch("/api/research", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      client_id: state.clientId,
      query,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    dom.researchStatusTag.textContent = "failed";
    dom.reportBox.textContent = payload.error || "研究任务提交失败";
    return;
  }
  state.researchJobId = payload.id;
  pollResearchJob(payload.id);
}

async function pollResearchJob(jobId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await delay(3000);
    const response = await fetch(`/api/research?job_id=${encodeURIComponent(jobId)}`);
    const payload = await response.json();
    dom.researchStatusTag.textContent = payload.status;
    if (payload.status === "completed" || payload.status === "failed") {
      dom.reportBox.textContent = payload.report_markdown || "无结果";
      return;
    }
    const step = payload.current_step ?? "?";
    const total = payload.total_steps ?? "?";
    dom.reportBox.textContent = `研究中... 状态：${payload.status}  步骤：${step}/${total}`;
  }
  dom.researchStatusTag.textContent = "timeout";
  dom.reportBox.textContent = "轮询超时，请稍后手动刷新研究结果接口。";
}

function appendMessage(role, content) {
  const node = dom.messageTemplate.content.firstElementChild.cloneNode(true);
  node.dataset.role = role;
  node.querySelector(".message-meta").textContent = role === "user" ? "你" : "TaskMate";
  node.querySelector(".message-body").textContent = content;
  dom.messageList.appendChild(node);
  dom.messageList.scrollTop = dom.messageList.scrollHeight;
}

function renderSelectedFilesHint() {
  if (state.selectedFileIds.size === 0) {
    dom.selectedFilesHint.textContent = "当前没有选中的文件上下文";
    return;
  }
  dom.selectedFilesHint.textContent = `本次聊天将带上 ${state.selectedFileIds.size} 个文件上下文`;
}

function loadOrCreateClientId() {
  const existing = localStorage.getItem(storageKeys.clientId);
  if (existing) return existing;
  const next = `client_${crypto.randomUUID().slice(0, 12)}`;
  localStorage.setItem(storageKeys.clientId, next);
  return next;
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result);
      const base64 = result.includes(",") ? result.split(",", 2)[1] : result;
      resolve(base64);
    };
    reader.onerror = () => reject(reader.error || new Error("FileReader failed"));
    reader.readAsDataURL(file);
  });
}

function guessContentType(filename) {
  if (filename.endsWith(".md")) return "text/markdown";
  if (filename.endsWith(".txt")) return "text/plain";
  if (filename.endsWith(".pdf")) return "application/pdf";
  if (filename.endsWith(".docx")) {
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  }
  return "application/octet-stream";
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
"""

UI_ASSETS = {
    "index.html": INDEX_HTML,
    "styles.css": STYLES_CSS,
    "app.js": APP_JS,
}
