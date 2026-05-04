const state = {
  mode: document.body.dataset.defaultMode || "aguardando_humano",
  selectedPhone: "",
  selectedName: "",
};

const conversationList = document.getElementById("conversationList");
const messageList = document.getElementById("messageList");
const modeFilter = document.getElementById("modeFilter");
const selectedName = document.getElementById("selectedName");
const selectedPhone = document.getElementById("selectedPhone");
const replyForm = document.getElementById("replyForm");
const replyText = document.getElementById("replyText");
const queueAlert = document.getElementById("queueAlert");
const defaultTitle = document.title;
let pendingConversations = 0;
let notificationPermissionAsked = false;

function escapeText(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
}

async function loadConversations() {
  const data = await api(`/operator/api/conversations?mode=${encodeURIComponent(state.mode)}`);
  pendingConversations = data.conversations.length;
  updateQueueAlert();
  maybeNotifyNewQueue(pendingConversations);
  conversationList.innerHTML = "";
  for (const item of data.conversations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `conversation-item${item.telefone === state.selectedPhone ? " active" : ""}`;
    button.innerHTML = `
      <strong>${escapeText(item.nome || "Cliente")}</strong>
      <span>${escapeText(item.telefone)}</span>
      <span class="preview">${escapeText(item.ultima_mensagem || "")}</span>
    `;
    button.addEventListener("click", () => selectConversation(item));
    conversationList.appendChild(button);
  }
}

function updateQueueAlert() {
  if (!queueAlert) {
    return;
  }
  if (pendingConversations > 0) {
    queueAlert.hidden = false;
    queueAlert.textContent = `${pendingConversations} conversa(s) aguardando operador`;
    document.title = `(${pendingConversations}) ${defaultTitle}`;
    return;
  }
  queueAlert.hidden = true;
  queueAlert.textContent = "Nenhuma conversa aguardando.";
  document.title = defaultTitle;
}

function beepAlert() {
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  gainNode.gain.value = 0.05;
  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);
  oscillator.start();
  oscillator.stop(audioContext.currentTime + 0.2);
}

let lastPendingConversations = 0;
function maybeNotifyNewQueue(currentPendingConversations) {
  if (currentPendingConversations <= lastPendingConversations) {
    lastPendingConversations = currentPendingConversations;
    return;
  }

  beepAlert();
  if (!("Notification" in window)) {
    lastPendingConversations = currentPendingConversations;
    return;
  }

  if (Notification.permission === "granted") {
    new Notification("LavPop Atendimento", {
      body: `Você tem ${currentPendingConversations} conversa(s) aguardando operador.`,
    });
  } else if (Notification.permission === "default" && !notificationPermissionAsked) {
    notificationPermissionAsked = true;
    Notification.requestPermission().catch(() => null);
  }
  lastPendingConversations = currentPendingConversations;
}

async function loadMessages() {
  if (!state.selectedPhone) {
    return;
  }
  const data = await api(`/operator/api/conversations/${encodeURIComponent(state.selectedPhone)}/messages`);
  messageList.innerHTML = "";
  for (const message of data.messages) {
    const node = document.createElement("article");
    node.className = `message ${message.direcao || ""}`;
    node.innerHTML = `
      <div class="message-meta">${escapeText(message.origem)} · ${escapeText(message.status)}</div>
      <div class="message-text">${escapeText(message.conteudo_texto)}</div>
    `;
    messageList.appendChild(node);
  }
  requestAnimationFrame(() => {
    messageList.scrollTop = messageList.scrollHeight;
  });
}

function selectConversation(item) {
  state.selectedPhone = item.telefone;
  state.selectedName = item.nome || "Cliente";
  selectedName.textContent = state.selectedName;
  selectedPhone.textContent = item.telefone;
  loadConversations().catch(console.error);
  loadMessages().catch(console.error);
}

async function postAction(action) {
  if (!state.selectedPhone) {
    return;
  }
  await api(`/operator/api/conversations/${encodeURIComponent(state.selectedPhone)}/${action}`, {
    method: "POST",
    body: "{}",
  });
  await loadConversations();
  await loadMessages();
}

document.getElementById("claimButton").addEventListener("click", () => postAction("claim").catch(alert));
document.getElementById("returnButton").addEventListener("click", () => postAction("return-to-bot").catch(alert));
document.getElementById("closeButton").addEventListener("click", () => postAction("close").catch(alert));

modeFilter.addEventListener("change", () => {
  state.mode = modeFilter.value;
  loadConversations().catch(console.error);
});

replyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedPhone || !replyText.value.trim()) {
    return;
  }
  await api(`/operator/api/conversations/${encodeURIComponent(state.selectedPhone)}/send`, {
    method: "POST",
    body: JSON.stringify({ text: replyText.value.trim() }),
  });
  replyText.value = "";
  await loadConversations();
  await loadMessages();
});

loadConversations().catch(console.error);
setInterval(() => {
  loadConversations().catch(console.error);
  loadMessages().catch(console.error);
}, 5000);
