const storageKeys = {
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
  messageInput: document.getElementById("messageInput"),
  messageList: document.getElementById("messageList"),
  taskList: document.getElementById("taskList"),
  fileList: document.getElementById("fileList"),
  reportBox: document.getElementById("reportBox"),
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
    appendMessage("assistant", payload.reply);

    await refreshTasks(payload.user_profile?.id);
    await refreshFiles();

    if (payload.intent === "deep_research") {
      await submitResearchJob(message);
    }
  } catch (error) {
    appendMessage("assistant", `请求失败：${error.message}`);
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
    dom.reportBox.textContent = "等待研究模式返回结果..."
    setResearchStatus("idle");
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
          <div class="file-stats">
            <span class="type-tag">${escapeHtml(file.content_type || guessContentType(file.filename))}</span>
            <span class="type-tag">向量 ${Number(file.vector_count || 0)}</span>
          </div>
          <p class="muted">${escapeHtml(file.summary || "暂无摘要")}</p>
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
  setResearchStatus("pending");
  dom.reportBox.textContent = "研究任务已提交，正在建立检索计划...";
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
    setResearchStatus("failed");
    dom.reportBox.textContent = payload.error || "研究任务提交失败";
    updateMessage(messageId, payload.error || "研究任务提交失败，请稍后重试。");
    return;
  }
  state.researchJobId = payload.id;
  await pollResearchJob(payload.id, messageId);
}

async function pollResearchJob(jobId, messageId) {
  for (let attempt = 0; attempt < RESEARCH_POLL_MAX_ATTEMPTS; attempt += 1) {
    await delay(RESEARCH_POLL_INTERVAL_MS);
    const response = await fetch(`/api/research?job_id=${encodeURIComponent(jobId)}`);
    const payload = await response.json();
    setResearchStatus(payload.status);
    if (payload.report_markdown) {
      dom.reportBox.textContent = payload.report_markdown;
    }
    updateMessage(messageId, "", {
      thinking: payload.status !== "completed" && payload.status !== "failed",
      thinkingLabel: researchThinkingLabel(payload.status),
    });
    if (payload.status === "completed" || payload.status === "failed") {
      if (payload.status === "completed") {
        updateMessage(messageId, "研究完成了。我已经把完整报告写到下方研究结果区，你可以继续追问其中任意一个子结论。");
      } else {
        updateMessage(messageId, "这次研究执行失败了。错误信息我已经同步到下方研究结果区。");
      }
      state.researchJobId = "";
      return;
    }
  }
  setResearchStatus("timeout");
  dom.reportBox.textContent = "自动轮询已持续 5 分钟，前端先停止等待。研究如果仍在后台执行，你可以稍后继续查看结果。";
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

function setResearchStatus(status) {
  dom.researchStatusTag.textContent = researchStatusLabel(status);
}

function researchStatusLabel(status) {
  const labels = {
    idle: "idle",
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
