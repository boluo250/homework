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
          <h1 id="assistantBrand">TaskMate</h1>
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
            <input
              id="fileInput"
              type="file"
              accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp,.gif,.mp3,.wav,.m4a,.ogg,.flac,.aac,.aiff,.aif,.mp4,.mov,.webm,.mpeg,.mpg,.m4v"
            />
            <button type="submit" class="ghost-button">上传文件</button>
          </form>
          <p id="uploadStatus" class="muted">
            支持 txt、md、pdf、docx、图片（含 webp/gif）、音频（mp3/wav 等）、视频（mp4/mov/webm 等），单文件最大 10MB；音视频与图片默认可通过
            OpenRouter MiMo Omni 抽取文本后入库。
          </p>
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

          <section id="researchDock" class="research-dock" data-state="idle">
            <div class="research-dock-header">
              <div class="research-dock-copy">
                <p class="eyebrow">Research Run</p>
                <h3>研究执行进度</h3>
              </div>
              <div class="panel-actions">
                <span id="researchStatusTag" class="badge">idle</span>
                <button id="copyReportButton" class="ghost-button" type="button">复制报告</button>
                <button id="exportReportButton" class="ghost-button" type="button">导出 Markdown</button>
              </div>
            </div>

            <div class="research-progress-card">
              <div class="research-progress-topline">
                <strong id="researchProgressTitle">等待新的研究任务</strong>
                <span id="researchProgressMeta" class="muted">尚未开始</span>
              </div>
              <div class="research-progress-track" aria-hidden="true">
                <div id="researchProgressFill" class="research-progress-fill"></div>
              </div>
            </div>

            <pre id="reportBox" class="report-box">等待研究模式返回结果...</pre>
          </section>

          <form id="chatForm" class="composer">
            <textarea
              id="messageInput"
              name="message"
              rows="3"
              placeholder="试试：帮我创建一个“简历优化”任务，下周五前完成，高优先级"
            ></textarea>
            <div class="composer-footer">
              <div class="composer-meta">
                <p id="selectedFilesHint" class="muted">当前没有选中的文件上下文</p>
                <p class="composer-hint">Enter 发送 · Shift+Enter 换行</p>
              </div>
              <button type="submit" class="primary-button">发送</button>
            </div>
          </form>
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
  min-height: 760px;
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

.panel-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
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
  min-height: 280px;
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

.message[data-thinking="true"] {
  background:
    radial-gradient(circle at top right, rgba(59, 124, 112, 0.12), transparent 28%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(244, 249, 247, 0.92));
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

.thinking-line {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 28px;
}

.thinking-label {
  font-weight: 600;
  color: var(--muted-strong);
}

.typing-dots {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(135deg, var(--accent), #7f66ff);
  opacity: 0.28;
  animation: thinkingPulse 1.1s ease-in-out infinite;
}

.typing-dots span:nth-child(2) {
  animation-delay: 0.14s;
}

.typing-dots span:nth-child(3) {
  animation-delay: 0.28s;
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

.composer-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.composer-footer .muted {
  margin-bottom: 0;
}

.composer-hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  letter-spacing: 0.01em;
}

.research-dock {
  margin: 0 16px;
  padding: 14px 16px 16px;
  border-radius: 24px;
  border: 1px solid var(--line);
  background:
    radial-gradient(circle at top right, rgba(200, 91, 61, 0.1), transparent 24%),
    linear-gradient(180deg, rgba(255, 252, 247, 0.9), rgba(250, 252, 249, 0.74));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.research-dock-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.research-dock-copy h3 {
  margin: 0;
  font-size: 17px;
  letter-spacing: -0.02em;
}

.research-dock-copy .eyebrow {
  margin-bottom: 6px;
}

.research-progress-card {
  padding: 12px 14px;
  border-radius: 20px;
  border: 1px solid rgba(24, 33, 38, 0.08);
  background: rgba(255, 255, 255, 0.66);
  box-shadow: var(--shadow-sm);
}

.research-progress-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.research-progress-topline strong {
  font-size: 14px;
  line-height: 1.4;
}

.research-progress-track {
  position: relative;
  width: 100%;
  height: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(24, 33, 38, 0.08);
}

.research-progress-fill {
  width: 0%;
  height: 100%;
  border-radius: inherit;
  background:
    linear-gradient(90deg, rgba(200, 91, 61, 0.94), rgba(59, 124, 112, 0.9));
  box-shadow: 0 0 24px rgba(200, 91, 61, 0.22);
  transition: width 220ms ease;
}

.report-box {
  min-height: 180px;
  max-height: 280px;
  margin: 12px 0 0;
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

.file-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
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

.research-dock .ghost-button {
  min-height: 30px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 600;
  border-color: rgba(24, 33, 38, 0.06);
  background: rgba(255, 255, 255, 0.5);
  box-shadow: none;
}

.research-dock .ghost-button:hover {
  background: rgba(255, 255, 255, 0.78);
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

@keyframes thinkingPulse {
  0%,
  100% {
    transform: translateY(0);
    opacity: 0.28;
  }

  50% {
    transform: translateY(-3px);
    opacity: 1;
  }
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

  .research-dock-header,
  .research-progress-topline {
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

  .research-dock,
  .composer {
    margin: 12px;
  }
}
"""
APP_JS = """const storageKeys = {
  clientId: "taskmate-client-id",
  conversationId: "taskmate-conversation-id",
  assistantName: "taskmate-assistant-name",
};

const RESEARCH_POLL_INTERVAL_MS = 2000;
const RESEARCH_POLL_TIMEOUT_MS = 5 * 60 * 1000;
const RESEARCH_POLL_MAX_ATTEMPTS = Math.ceil(RESEARCH_POLL_TIMEOUT_MS / RESEARCH_POLL_INTERVAL_MS);

const state = {
  clientId: loadOrCreateClientId(),
  conversationId: localStorage.getItem(storageKeys.conversationId) || "",
  assistantName: localStorage.getItem(storageKeys.assistantName) || "TaskMate",
  selectedFileIds: new Set(),
  researchJobId: "",
  researchMessageId: "",
  isComposing: false,
};

const dom = {
  chatForm: document.getElementById("chatForm"),
  submitButton: document.querySelector("#chatForm .primary-button"),
  messageInput: document.getElementById("messageInput"),
  messageList: document.getElementById("messageList"),
  taskList: document.getElementById("taskList"),
  fileList: document.getElementById("fileList"),
  researchDock: document.getElementById("researchDock"),
  reportBox: document.getElementById("reportBox"),
  researchProgressTitle: document.getElementById("researchProgressTitle"),
  researchProgressMeta: document.getElementById("researchProgressMeta"),
  researchProgressFill: document.getElementById("researchProgressFill"),
  refreshTasksButton: document.getElementById("refreshTasksButton"),
  newConversationButton: document.getElementById("newConversationButton"),
  resetDataButton: document.getElementById("resetDataButton"),
  clientIdTag: document.getElementById("clientIdTag"),
  assistantBrand: document.getElementById("assistantBrand"),
  messageTemplate: document.getElementById("messageTemplate"),
  uploadForm: document.getElementById("uploadForm"),
  fileInput: document.getElementById("fileInput"),
  uploadStatus: document.getElementById("uploadStatus"),
  researchStatusTag: document.getElementById("researchStatusTag"),
  selectedFilesHint: document.getElementById("selectedFilesHint"),
  copyReportButton: document.getElementById("copyReportButton"),
  exportReportButton: document.getElementById("exportReportButton"),
};

dom.clientIdTag.textContent = `client_id: ${state.clientId}`;
applyAssistantIdentity(state.assistantName);
renderResearchState({ status: "idle", report_markdown: "等待研究模式返回结果..." });
initializeWorkspace();

dom.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitChat();
});

dom.messageInput.addEventListener("compositionstart", () => {
  state.isComposing = true;
});

dom.messageInput.addEventListener("compositionend", () => {
  state.isComposing = false;
});

dom.messageInput.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing || state.isComposing) {
    return;
  }
  event.preventDefault();
  await submitChat();
});

async function submitChat() {
  const message = dom.messageInput.value.trim();
  if (!message) return;

  appendMessage("user", message);
  dom.messageInput.value = "";
  const pendingMessageId = appendMessage("assistant", "", {
    thinking: true,
    thinkingLabel: pendingChatLabel(message),
  });
  setComposerBusy(true);

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
    if (payload.assistant_name) {
      applyAssistantIdentity(payload.assistant_name);
    }
    updateMessage(pendingMessageId, payload.reply);

    await refreshTasks(payload.user_profile?.id);
    await refreshFiles();

    if (payload.intent === "deep_research") {
      await submitResearchJob(message);
    }
  } catch (error) {
    updateMessage(pendingMessageId, `请求失败：${error.message}`);
  } finally {
    setComposerBusy(false);
  }
}

dom.refreshTasksButton.addEventListener("click", async () => {
  await refreshTasks();
});

dom.newConversationButton.addEventListener("click", () => {
  state.conversationId = "";
  localStorage.removeItem(storageKeys.conversationId);
  dom.messageList.innerHTML = "";
  appendMessage("assistant", "已经为你开启一个新会话。");
});

dom.copyReportButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(dom.reportBox.textContent || "");
    setResearchStatus("copied");
  } catch (_error) {
    setResearchStatus("copy_failed");
  }
});

dom.exportReportButton.addEventListener("click", () => {
  const blob = new Blob([dom.reportBox.textContent || ""], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `taskmate-research-${Date.now()}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
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
    renderResearchState({ status: "idle", report_markdown: "等待研究模式返回结果..." });
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
    dom.uploadStatus.textContent = `正在读取 ${file.name}...`;
    const contentBase64 = await readFileAsBase64(file);
    dom.uploadStatus.textContent = `正在上传 ${file.name} 到 Worker...`;
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
    dom.uploadStatus.textContent = `解析与向量化完成：${payload.file.filename}，共切分 ${payload.chunk_count} 个片段，Qdrant 已写入 ${payload.vector_count} 条向量。`;
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
      ${task.details ? `<p class="muted">${escapeHtml(task.details)}</p>` : ""}
      <p class="muted">status: ${statusLabel(task.status)}</p>
      <p class="muted">due: ${task.due_at || "n/a"}</p>
      <p class="muted">updated: ${formatDate(task.updated_at)}</p>
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
        <button class="ghost-button" type="button" data-rename-file-id="${escapeHtml(file.id)}">重命名</button>
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

  dom.fileList.querySelectorAll("[data-rename-file-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const fileId = button.dataset.renameFileId;
      const currentName = button.closest(".file-card")?.querySelector("strong")?.textContent || "";
      const nextName = window.prompt("输入新的文件名（需保持扩展名不变）", currentName);
      if (!nextName || nextName === currentName) {
        return;
      }
      await renameFile(fileId, nextName);
    });
  });

  renderSelectedFilesHint();
}

async function renameFile(fileId, filename) {
  dom.uploadStatus.textContent = `正在重命名为 ${filename}...`;
  const response = await fetch("/api/files", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      client_id: state.clientId,
      file_id: fileId,
      filename,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    dom.uploadStatus.textContent = `重命名失败：${payload.error || "Unknown error"}`;
    return;
  }
  dom.uploadStatus.textContent = `已重命名文件：${payload.file.filename}`;
  await refreshFiles();
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
  const messageId = `research_${crypto.randomUUID().slice(0, 8)}`;
  state.researchMessageId = messageId;
  renderResearchState({
    status: "pending",
    phase: "pending",
    current_step: 0,
    total_steps: 0,
    report_markdown: "研究任务已提交，正在建立检索计划...",
  });
  appendMessage("assistant", "", {
    messageId,
    thinking: true,
    thinkingLabel: researchThinkingLabel("pending"),
  });
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
    renderResearchState({
      status: "failed",
      phase: "failed",
      report_markdown: payload.error || "研究任务提交失败",
    });
    updateMessage(messageId, payload.error || "研究任务提交失败，请稍后重试。");
    return;
  }
  state.researchJobId = payload.id;
  renderResearchState(payload);
  await pollResearchJob(payload.id, messageId);
}

async function pollResearchJob(jobId, messageId) {
  for (let attempt = 0; attempt < RESEARCH_POLL_MAX_ATTEMPTS; attempt += 1) {
    await delay(RESEARCH_POLL_INTERVAL_MS);
    const response = await fetch(`/api/research?job_id=${encodeURIComponent(jobId)}`);
    const payload = await response.json();
    const phase = payload.phase || payload.state?.phase || payload.status;
    renderResearchState(payload);
    updateMessage(messageId, "", {
      thinking: payload.status !== "completed" && payload.status !== "failed",
      thinkingLabel: researchThinkingLabel(phase),
    });
    if (payload.status === "completed" || payload.status === "failed") {
      if (payload.status === "completed") {
        updateMessage(messageId, "研究完成了。我已经把完整报告写进当前对话面板里的研究卡片，你可以继续追问其中任意一个子结论。");
      } else {
        updateMessage(messageId, "这次研究执行失败了。错误信息我已经同步到当前对话面板里的研究卡片。");
      }
      state.researchJobId = "";
      return;
    }
  }
  renderResearchState({
    status: "timeout",
    phase: "timeout",
    report_markdown: "自动轮询已持续 5 分钟，前端先停止等待。研究如果仍在后台执行，你可以稍后继续查看结果。",
  });
  updateMessage(messageId, "我已经持续轮询了 5 分钟。前端先停止自动等待，但如果后台还在跑，稍后再进入页面或继续发消息时仍可以继续查看结果。");
}

function appendMessage(role, content, options = {}) {
  const node = dom.messageTemplate.content.firstElementChild.cloneNode(true);
  node.dataset.role = role;
  node.dataset.messageId = options.messageId || `msg_${crypto.randomUUID().slice(0, 8)}`;
  node.querySelector(".message-meta").textContent = role === "user" ? "你" : state.assistantName;
  setMessageContent(node, content, options);
  dom.messageList.appendChild(node);
  dom.messageList.scrollTop = dom.messageList.scrollHeight;
  return node.dataset.messageId;
}

function updateMessage(messageId, content, options = {}) {
  const node = Array.from(dom.messageList.querySelectorAll(".message")).find(
    (item) => item.dataset.messageId === messageId,
  );
  if (!node) return;
  setMessageContent(node, content, options);
  dom.messageList.scrollTop = dom.messageList.scrollHeight;
}

function setMessageContent(node, content, options = {}) {
  const body = node.querySelector(".message-body");
  if (options.thinking) {
    node.dataset.thinking = "true";
    body.innerHTML = `
      <div class="thinking-line">
        <span class="thinking-label">${escapeHtml(options.thinkingLabel || "正在思考")}</span>
        <span class="typing-dots" aria-hidden="true">
          <span></span><span></span><span></span>
        </span>
      </div>
    `;
    return;
  }
  delete node.dataset.thinking;
  body.textContent = content;
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

async function initializeWorkspace() {
  appendMessage("assistant", `你好，我是 ${state.assistantName}，我已经准备好接住任务、研究请求和文件问答了。`);
  appendMessage(
    "assistant",
    "首次使用建议：先告诉我你的名字和邮箱，再试试创建一个带具体要求的任务、上传一份文件，或者发起一个研究主题。",
  );
  await refreshSessionMeta();
  await refreshTasks();
  await refreshFiles();
  renderSelectedFilesHint();
}

async function refreshSessionMeta() {
  try {
    const response = await fetch(`/api/chat?client_id=${encodeURIComponent(state.clientId)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Load session failed");
    }
    if (payload.assistant_name) {
      applyAssistantIdentity(payload.assistant_name);
    }
    if (!payload.user_profile?.name || !payload.user_profile?.email) {
      appendMessage("assistant", "开始之前，先把你的名字和邮箱告诉我，我会在后续对话里持续记住。");
    }
  } catch (_error) {
    // Keep the optimistic local identity if session bootstrap fails.
  }
}

function applyAssistantIdentity(name) {
  state.assistantName = name || "TaskMate";
  localStorage.setItem(storageKeys.assistantName, state.assistantName);
  document.title = `${state.assistantName} Worker Demo`;
  if (dom.assistantBrand) {
    dom.assistantBrand.textContent = state.assistantName;
  }
}

function setComposerBusy(isBusy) {
  if (dom.submitButton) {
    dom.submitButton.disabled = isBusy;
    dom.submitButton.textContent = isBusy ? "处理中..." : "发送";
  }
  dom.messageInput.disabled = isBusy;
}

function pendingChatLabel(message) {
  const lowered = message.toLowerCase();
  if (state.selectedFileIds.size > 0 || /文档|文件|pdf|docx|总结|概括|归纳/.test(message)) {
    return "正在整理文件内容";
  }
  if (/研究|调研|对比|方案|报告|分析/.test(message)) {
    return "正在准备研究计划";
  }
  if (/任务|待办|todo|提醒/.test(lowered) || /任务|待办|提醒/.test(message)) {
    return "正在处理任务请求";
  }
  return "正在思考";
}

function setResearchStatus(status) {
  dom.researchStatusTag.textContent = researchStatusLabel(status);
  if (dom.researchDock) {
    dom.researchDock.dataset.state = status || "idle";
  }
}

function renderResearchState(payload = {}) {
  const phase = payload.phase || payload.state?.phase || payload.status || "idle";
  const status = payload.status || phase || "idle";
  const currentStep = Number(payload.current_step ?? payload.state?.current_step ?? 0);
  const totalSteps = Number(payload.total_steps ?? payload.state?.total_steps ?? 0);
  const percent = researchProgressPercent({ status, phase, currentStep, totalSteps });
  const title = researchProgressTitle({ status, phase, currentStep, totalSteps });
  const meta = researchProgressMeta({ status, phase, currentStep, totalSteps, percent });
  const reportText = payload.report_markdown || (status === "idle" ? "等待研究模式返回结果..." : dom.reportBox.textContent);

  setResearchStatus(phase);
  dom.researchProgressTitle.textContent = title;
  dom.researchProgressMeta.textContent = meta;
  dom.researchProgressFill.style.width = `${percent}%`;
  dom.reportBox.textContent = reportText;
}

function researchProgressPercent({ status, phase, currentStep, totalSteps }) {
  if (status === "completed") return 100;
  if (status === "failed") {
    return totalSteps > 0 ? Math.max(12, Math.round((currentStep / totalSteps) * 100)) : 100;
  }
  if (status === "timeout") return 100;
  if (status === "pending") return 6;
  if (phase === "synthesizing") {
    return totalSteps > 0 ? Math.min(98, Math.round(((Math.max(currentStep, totalSteps - 0.25)) / totalSteps) * 100)) : 88;
  }
  if (phase === "searching") {
    return totalSteps > 0 ? Math.min(94, Math.round(((currentStep + 0.55) / totalSteps) * 100)) : 28;
  }
  if (phase === "queued") {
    return totalSteps > 0 ? Math.max(8, Math.round((currentStep / totalSteps) * 100)) : 8;
  }
  return 0;
}

function researchProgressTitle({ status, phase, currentStep, totalSteps }) {
  if (status === "completed") return "研究完成，报告已生成";
  if (status === "failed") return "研究执行失败";
  if (status === "timeout") return "前端已停止自动轮询";
  if (status === "pending") return "研究任务已提交，正在建立计划";
  if (phase === "synthesizing") return "正在汇总最终报告";
  if (phase === "searching" && totalSteps > 0) {
    return `正在执行第 ${Math.min(currentStep + 1, totalSteps)} / ${totalSteps} 步`;
  }
  if (phase === "queued" && totalSteps > 0) {
    return `已完成 ${currentStep} / ${totalSteps} 步，准备进入下一阶段`;
  }
  return "等待新的研究任务";
}

function researchProgressMeta({ status, phase, currentStep, totalSteps, percent }) {
  if (status === "idle") return "尚未开始";
  if (totalSteps > 0) {
    return `${researchStatusLabel(phase)} · ${currentStep}/${totalSteps} · ${percent}%`;
  }
  return `${researchStatusLabel(phase)} · ${percent}%`;
}

function researchStatusLabel(status) {
  const labels = {
    idle: "idle",
    queued: "排队中",
    pending: "已提交",
    planning: "规划中",
    searching: "检索中",
    reading: "阅读中",
    synthesizing: "汇总中",
    completed: "已完成",
    failed: "失败",
    timeout: "超时",
    copied: "已复制",
    copy_failed: "复制失败",
  };
  return labels[status] || status;
}

function researchThinkingLabel(status) {
  const labels = {
    queued: "正在等待后台消费者接手",
    pending: "正在接住研究任务",
    planning: "正在拆解研究问题",
    searching: "正在搜索网页资料",
    reading: "正在阅读和整理证据",
    synthesizing: "正在汇总结论与建议",
  };
  return labels[status] || "正在研究中";
}

function escapeHtml(input) {
  return String(input)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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
  if (filename.endsWith(".png")) return "image/png";
  if (filename.endsWith(".jpg") || filename.endsWith(".jpeg")) return "image/jpeg";
  return "application/octet-stream";
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatDate(value) {
  if (!value) return "n/a";
  return value.replace("T", " ").replace("+00:00", " UTC");
}

function statusLabel(value) {
  if (value === "todo") return "待办";
  if (value === "in_progress") return "进行中";
  if (value === "done") return "已完成";
  return value || "unknown";
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
