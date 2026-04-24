const storageKeys = {
  clientId: "taskmate-client-id",
  conversationId: "taskmate-conversation-id",
  assistantName: "taskmate-assistant-name",
  userName: "taskmate-user-name",
  userEmail: "taskmate-user-email",
};

const RESEARCH_POLL_INTERVAL_MS = 2000;
const RESEARCH_POLL_TIMEOUT_MS = 5 * 60 * 1000;
const RESEARCH_POLL_MAX_ATTEMPTS = Math.ceil(RESEARCH_POLL_TIMEOUT_MS / RESEARCH_POLL_INTERVAL_MS);

const state = {
  clientId: loadOrCreateClientId(),
  conversationId: localStorage.getItem(storageKeys.conversationId) || "",
  assistantName: localStorage.getItem(storageKeys.assistantName) || "TaskMate",
  userProfile: loadUserProfile(),
  selectedFileIds: new Set(),
  activeFileId: "",
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
  fileDetailCard: document.getElementById("fileDetailCard"),
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
  dom.messageInput.value = "";
  await sendChatMessage(message);
}

async function sendChatMessage(message) {
  appendMessage("user", message);
  const pendingMessageId = appendMessage("assistant", "", {
    thinking: true,
    thinkingLabel: pendingChatLabel(message),
  });
  setComposerBusy(true);

  try {
    const payload = await requestChatStream(message, pendingMessageId);
    syncChatPayload(payload);
    if (!payload.reply) {
      updateMessage(pendingMessageId, "");
    }

    await refreshTasks(payload.user_profile?.id);
    await refreshFiles();

    if (payload.intent === "deep_research") {
      await submitResearchJob(message);
    }
    return payload;
  } catch (error) {
    updateMessage(pendingMessageId, `请求失败：${error.message}`);
    return null;
  } finally {
    setComposerBusy(false);
  }
}

function buildChatPayload(message) {
  return {
    client_id: state.clientId,
    conversation_id: state.conversationId || null,
    message,
    file_ids: Array.from(state.selectedFileIds),
  };
}

function syncChatPayload(payload) {
  if (!payload) {
    return;
  }
  if (payload.conversation_id) {
    state.conversationId = payload.conversation_id;
    localStorage.setItem(storageKeys.conversationId, state.conversationId);
  }
  if (payload.assistant_name) {
    applyAssistantIdentity(payload.assistant_name);
  }
  if (payload.user_profile) {
    applyUserProfile(payload.user_profile);
  }
}

async function requestChatStream(message, pendingMessageId) {
  const requestStartedAt = Date.now();
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(buildChatPayload(message)),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  if (!response.body) {
    const payload = await requestChatJson(message);
    updateMessage(pendingMessageId, payload.reply || "");
    return payload;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let reply = "";
  let finalPayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    ({ buffer, reply, finalPayload } = applySseBlocks(buffer, {
      pendingMessageId,
      reply,
      finalPayload,
      requestStartedAt,
    }));
  }

  ({ buffer, reply, finalPayload } = applySseBlocks(buffer, {
    pendingMessageId,
    reply,
    finalPayload,
    flush: true,
    requestStartedAt,
  }));

  if (!finalPayload) {
    throw new Error("流式响应未正常结束");
  }
  if (finalPayload.reply && finalPayload.reply !== reply) {
    updateMessage(pendingMessageId, finalPayload.reply);
  }
  return finalPayload;
}

function applySseBlocks(rawBuffer, stateSnapshot) {
  let buffer = rawBuffer;
  let reply = stateSnapshot.reply || "";
  let finalPayload = stateSnapshot.finalPayload || null;
  const chunks = buffer.split("\n\n");
  if (!stateSnapshot.flush) {
    buffer = chunks.pop() || "";
  } else {
    buffer = "";
  }

  for (const chunk of chunks) {
    const parsed = parseSseEvent(chunk);
    if (!parsed) {
      continue;
    }
    if (parsed.event === "status") {
      updateMessage(stateSnapshot.pendingMessageId, "", {
        thinking: true,
        thinkingLabel: parsed.data.label || "正在思考",
      });
      continue;
    }
    if (parsed.event === "meta") {
      syncChatPayload(parsed.data);
      continue;
    }
    if (parsed.event === "probe") {
      const elapsedMs = Date.now() - (stateSnapshot.requestStartedAt || Date.now());
      console.info("[taskmate] stream probe", {
        stage: parsed.data.stage || "unknown",
        elapsed_ms: elapsedMs,
        hit_count: parsed.data.hit_count ?? null,
      });
      if (!reply && parsed.data.preview) {
        updateMessage(stateSnapshot.pendingMessageId, parsed.data.preview);
      }
      continue;
    }
    if (parsed.event === "delta") {
      reply += parsed.data.text || "";
      updateMessage(stateSnapshot.pendingMessageId, reply);
      continue;
    }
    if (parsed.event === "done") {
      finalPayload = parsed.data;
      continue;
    }
    if (parsed.event === "error") {
      throw new Error(parsed.data.error || "流式请求失败");
    }
  }

  return { buffer, reply, finalPayload };
}

function parseSseEvent(block) {
  const lines = String(block || "")
    .split("\n")
    .map((line) => line.trimEnd())
    .filter(Boolean);
  if (lines.length === 0) {
    return null;
  }
  let event = "message";
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  const rawData = dataLines.join("\n");
  if (!rawData) {
    return null;
  }
  return {
    event,
    data: JSON.parse(rawData),
  };
}

async function requestChatJson(message) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(buildChatPayload(message)),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

async function readErrorMessage(response) {
  const rawText = await response.text();
  try {
    const payload = JSON.parse(rawText);
    return payload.error || rawText || "Request failed";
  } catch (_error) {
    return rawText || "Request failed";
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
    applyAssistantIdentity("TaskMate");
    applyUserProfile(null);
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
    if (payload.ingest_status === "queued") {
      dom.uploadStatus.textContent = `已保存 ${payload.file.filename}。视频转写与向量化在后台队列中处理（避免 Worker CPU 超时），请稍后刷新文件列表查看进度。`;
    } else {
      dom.uploadStatus.textContent = `解析与向量化完成：${payload.file.filename}，共切分 ${payload.chunk_count} 个片段，Qdrant 已写入 ${payload.vector_count} 条向量。`;
    }
    dom.fileInput.value = "";
    await refreshFiles(payload.user_id);
    await loadFileDetails(payload.file.id, payload.user_id);
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
      <div class="task-meta-grid">
        <p class="muted">status: ${statusLabel(task.status)}</p>
        <p class="muted">start: ${task.start_at || "n/a"}</p>
        <p class="muted">end: ${task.end_at || task.due_at || "n/a"}</p>
        <p class="muted">updated: ${formatDate(task.updated_at)}</p>
      </div>
      <div class="task-actions">
        <button class="ghost-button" type="button" data-edit-task-id="${escapeHtml(task.id)}">AI 修改</button>
      </div>
    `;
    dom.taskList.appendChild(card);
  }

  dom.taskList.querySelectorAll("[data-edit-task-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const taskId = button.dataset.editTaskId;
      const task = payload.tasks.find((item) => item.id === taskId);
      if (!task) {
        return;
      }
      await editTask(task);
    });
  });
}

async function editTask(task) {
  const instruction = window.prompt(
    "告诉 AI 你想怎么修改这个任务。示例：标题改成“面试作业终版”，优先级改高，状态改成进行中，开始日期改成 2026-05-01，结束日期改成 2026-05-03",
    "",
  );
  if (instruction === null || !instruction.trim()) {
    return;
  }

  const message = [
    `请帮我修改任务“${task.title}”。`,
    "当前任务信息：",
    `- 标题：${task.title}`,
    `- 状态：${task.status}`,
    `- 优先级：${task.priority}`,
    `- 开始日期：${task.start_at || "未设置"}`,
    `- 结束日期：${task.end_at || task.due_at || "未设置"}`,
    `- 具体需求：${task.details || "暂无具体需求"}`,
    "",
    "修改要求：",
    instruction.trim(),
    "",
    "只修改我明确提到的字段，其余字段保持不变。",
  ].join("\n");

  await sendChatMessage(message);
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
    state.activeFileId = "";
    renderFileDetails();
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
        <button class="ghost-button" type="button" data-view-file-id="${escapeHtml(file.id)}">查看详情</button>
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

  dom.fileList.querySelectorAll("[data-view-file-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const fileId = button.dataset.viewFileId;
      await loadFileDetails(fileId);
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
  if (state.activeFileId && validIds.has(state.activeFileId)) {
    await loadFileDetails(state.activeFileId, payload.user_id || resolvedUserId, { silent: true });
  } else {
    const [firstFile] = payload.files;
    state.activeFileId = firstFile?.id || "";
    if (state.activeFileId) {
      await loadFileDetails(state.activeFileId, payload.user_id || resolvedUserId, { silent: true });
    } else {
      renderFileDetails();
    }
  }
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
  await loadFileDetails(fileId);
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
  if (state.activeFileId === fileId) {
    state.activeFileId = "";
  }
  dom.uploadStatus.textContent = `已删除文件：${payload.deleted.filename}`;
  await refreshFiles();
}

async function loadFileDetails(fileId, userId = "", options = {}) {
  if (!fileId) {
    state.activeFileId = "";
    renderFileDetails();
    return;
  }
  state.activeFileId = fileId;
  if (!options.silent) {
    renderFileDetails({ loading: true });
  }

  const resolvedUserId = userId || window.__taskmateLastUserId || "";
  const query = resolvedUserId
    ? `user_id=${encodeURIComponent(resolvedUserId)}&file_id=${encodeURIComponent(fileId)}`
    : `client_id=${encodeURIComponent(state.clientId)}&file_id=${encodeURIComponent(fileId)}`;
  const response = await fetch(`/api/files?${query}`);
  const payload = await response.json();
  if (!response.ok) {
    renderFileDetails({ error: payload.error || "加载文件详情失败" });
    return;
  }
  renderFileDetails(payload);
}

function renderFileDetails(payload = {}) {
  if (payload.loading) {
    dom.fileDetailCard.className = "file-detail-card";
    dom.fileDetailCard.innerHTML = "<p class=\"muted\">正在加载文件详情...</p>";
    return;
  }
  if (payload.error) {
    dom.fileDetailCard.className = "file-detail-card";
    dom.fileDetailCard.innerHTML = `<p class="muted">文件详情加载失败：${escapeHtml(payload.error)}</p>`;
    return;
  }
  if (!payload.file) {
    dom.fileDetailCard.className = "file-detail-card empty-state";
    dom.fileDetailCard.textContent = "选择一个文件后，这里会展示文件详情和内容预览。";
    return;
  }

  const file = payload.file;
  const previewText = payload.preview_text || file.summary || "当前没有可展示的文本预览。";
  dom.fileDetailCard.className = "file-detail-card";
  dom.fileDetailCard.innerHTML = `
    <h3>${escapeHtml(file.filename)}</h3>
    <div class="file-detail-meta muted">
      <span>类型：${escapeHtml(file.content_type || "unknown")}</span>
      <span>大小：${formatFileSize(file.size_bytes || 0)}</span>
      <span>向量数：${payload.vector_count ?? 0}</span>
      <span>创建时间：${formatDate(file.created_at)}</span>
    </div>
    <pre class="file-preview">${escapeHtml(previewText)}</pre>
  `;
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
  node.querySelector(".message-meta").textContent = role === "user" ? (state.userProfile?.name || "你") : state.assistantName;
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

function loadUserProfile() {
  const name = localStorage.getItem(storageKeys.userName) || "";
  const email = localStorage.getItem(storageKeys.userEmail) || "";
  if (!name && !email) {
    return null;
  }
  return { name, email };
}

function syncComposerPlaceholder() {
  if (!dom.messageInput) {
    return;
  }
  const missing = missingProfileFields(state.userProfile);
  if (missing.length > 0) {
    dom.messageInput.placeholder = `先告诉我你的${missing.join("和")}，例如：我叫小李，邮箱是 xiaoli@example.com`;
    return;
  }
  dom.messageInput.placeholder = `${state.userProfile.name}，试试：帮我创建一个我的待办“简历优化”，下周五前完成，高优先级`;
}

function buildBootstrapMessage() {
  const missing = missingProfileFields(state.userProfile);
  if (missing.length > 0) {
    return `你好，我是 ${state.assistantName}。开始之前，先告诉我你的${missing.join("和")}，我会先记下来，后续就能稳定称呼你。`;
  }
  return `你好，${state.userProfile.name}，我是 ${state.assistantName}。你的名字和邮箱我已经记住了，可以继续创建你的待办、上传文件，或者直接发起研究。`;
}

function missingProfileFields(profile) {
  const missing = [];
  if (!profile?.name) {
    missing.push("名字");
  }
  if (!profile?.email) {
    missing.push("邮箱");
  }
  return missing;
}

function refreshMessageMetaLabels() {
  dom.messageList.querySelectorAll(".message").forEach((node) => {
    const meta = node.querySelector(".message-meta");
    if (!meta) {
      return;
    }
    meta.textContent = node.dataset.role === "user" ? (state.userProfile?.name || "你") : state.assistantName;
  });
}

async function initializeWorkspace() {
  syncComposerPlaceholder();
  refreshMessageMetaLabels();
  await refreshSessionMeta({ bootstrap: true });
  await refreshTasks();
  await refreshFiles();
  renderSelectedFilesHint();
}

async function refreshSessionMeta(options = {}) {
  try {
    const response = await fetch(`/api/chat?client_id=${encodeURIComponent(state.clientId)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Load session failed");
    }
    if (payload.assistant_name) {
      applyAssistantIdentity(payload.assistant_name);
    }
    applyUserProfile(payload.user_profile || null);
    if (options.bootstrap) {
      appendMessage("assistant", buildBootstrapMessage());
    }
    return payload;
  } catch (_error) {
    // Keep the optimistic local identity if session bootstrap fails.
    if (options.bootstrap) {
      appendMessage("assistant", buildBootstrapMessage());
    }
    return null;
  }
}

function applyAssistantIdentity(name) {
  state.assistantName = name || "TaskMate";
  localStorage.setItem(storageKeys.assistantName, state.assistantName);
  document.title = `${state.assistantName} Worker Demo`;
  if (dom.assistantBrand) {
    dom.assistantBrand.textContent = state.assistantName;
  }
  refreshMessageMetaLabels();
}

function applyUserProfile(profile) {
  state.userProfile = profile && (profile.name || profile.email) ? profile : null;
  if (state.userProfile?.name) {
    localStorage.setItem(storageKeys.userName, state.userProfile.name);
  } else {
    localStorage.removeItem(storageKeys.userName);
  }
  if (state.userProfile?.email) {
    localStorage.setItem(storageKeys.userEmail, state.userProfile.email);
  } else {
    localStorage.removeItem(storageKeys.userEmail);
  }
  syncComposerPlaceholder();
  refreshMessageMetaLabels();
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
  if (/我的任务|我的待办|待办|提醒我|帮我创建|给我记/.test(message) || /todo/.test(lowered)) {
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
  const profileLabel = payload.research_profile_label || "通用研究";
  const subRuns = Array.isArray(payload.sub_runs) ? payload.sub_runs : [];
  const percent = researchProgressPercent({ status, phase, currentStep, totalSteps });
  const title = researchProgressTitle({ status, phase, currentStep, totalSteps });
  const meta = researchProgressMeta({ status, phase, currentStep, totalSteps, percent, profileLabel, subRuns });
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

function researchProgressMeta({ status, phase, currentStep, totalSteps, percent, profileLabel, subRuns }) {
  if (status === "idle") return "尚未开始";
  const runSummary = subRuns.length > 0
    ? `子代理 ${subRuns.filter((item) => item.status === "completed").length}/${subRuns.length}`
    : null;
  if (totalSteps > 0) {
    return [profileLabel, researchStatusLabel(phase), `${currentStep}/${totalSteps}`, runSummary, `${percent}%`]
      .filter(Boolean)
      .join(" · ");
  }
  return [profileLabel, researchStatusLabel(phase), runSummary, `${percent}%`]
    .filter(Boolean)
    .join(" · ");
}

function researchStatusLabel(status) {
  const labels = {
    idle: "idle",
    queued: "排队中",
    pending: "已提交",
    planning: "规划中",
    orchestrating: "编排中",
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
    orchestrating: "正在编排子代理",
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

function formatFileSize(sizeBytes) {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return "0 B";
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
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
