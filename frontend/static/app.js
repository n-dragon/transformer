// ImmoAgent frontend — chat + agent configurator

const API_BASE = "";

let conversationHistory = [];
let activeAgent = null;
let selectedRooms = 0;
let isStreaming = false;

// ─── Init ───────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadSites();
  setupTextarea();
  setupRoomButtons();
  setupAgentForm();
});

// ─── Sites list ─────────────────────────────────────────
async function loadSites() {
  try {
    const resp = await fetch(`${API_BASE}/api/sites`);
    const data = await resp.json();
    renderSites(data.sites);
  } catch (e) {
    document.getElementById("sitesList").innerHTML =
      '<div class="loading-sites">Impossible de charger les sites</div>';
  }
}

function renderSites(sites) {
  const container = document.getElementById("sitesList");
  container.innerHTML = sites.map(site => {
    const antiBotClass = {
      "Faible": "anti-bot-low",
      "Modéré": "anti-bot-med",
      "Fort": "anti-bot-high",
      "Fort (DataDome)": "anti-bot-high",
    }[site.anti_bot] || "anti-bot-med";

    return `
      <div class="site-item" onclick="window.open('${site.url}', '_blank')">
        <div class="site-item-header">
          <span class="site-item-name">${site.name}</span>
          <span class="anti-bot-badge ${antiBotClass}">${site.anti_bot}</span>
        </div>
        <div class="site-item-desc">${site.description}</div>
        <div class="site-item-country">${site.country}</div>
      </div>
    `;
  }).join("");
}

// ─── Agent form ─────────────────────────────────────────
function setupAgentForm() {
  document.getElementById("agentForm").addEventListener("submit", (e) => {
    e.preventDefault();
    createAgent();
  });
}

function createAgent() {
  const name = document.getElementById("agentName").value || "Mon agent";
  const listingType = document.querySelector('input[name="listingType"]:checked').value;
  const location = document.getElementById("location").value || "paris";
  const propertyType = document.getElementById("propertyType").value;
  const maxPrice = document.getElementById("maxPrice").value;
  const minSurface = document.getElementById("minSurface").value;
  const sites = [...document.querySelectorAll('input[name="sites"]:checked')].map(el => el.value);

  activeAgent = { name, listingType, location, propertyType, maxPrice, minSurface, rooms: selectedRooms, sites };

  document.getElementById("currentAgentName").textContent = `🤖 ${name}`;
  const typeLabel = listingType === "rent" ? "Location" : "Achat";
  const priceLabel = maxPrice ? ` — max ${Number(maxPrice).toLocaleString("fr-FR")} €` : "";
  const surfLabel = minSurface ? ` — min ${minSurface} m²` : "";
  document.getElementById("currentAgentDesc").textContent =
    `${typeLabel} · ${location}${priceLabel}${surfLabel} · Sites: ${sites.join(", ") || "aucun"}`;

  conversationHistory = [];
  clearMessages();

  const initialMessage = buildInitialMessage(activeAgent);
  sendMessageToAPI(initialMessage);
}

function buildInitialMessage(agent) {
  const typeLabel = agent.listingType === "rent" ? "louer" : "acheter";
  const parts = [`Je cherche à ${typeLabel} un bien à ${agent.location}`];
  if (agent.propertyType !== "any") {
    const typeMap = { apartment: "appartement", house: "maison", studio: "studio" };
    parts.push(`de type ${typeMap[agent.propertyType] || agent.propertyType}`);
  }
  if (agent.maxPrice) parts.push(`avec un budget maximum de ${Number(agent.maxPrice).toLocaleString("fr-FR")} €`);
  if (agent.minSurface) parts.push(`d'une surface minimale de ${agent.minSurface} m²`);
  if (agent.rooms > 0) parts.push(`avec au moins ${agent.rooms} pièce(s)`);
  if (agent.sites.length > 0) parts.push(`Cherche sur : ${agent.sites.join(", ")}`);

  return parts.join(", ") + ". Trouve-moi les meilleures annonces correspondantes et fais-moi une analyse.";
}

// ─── Rooms selector ─────────────────────────────────────
function setupRoomButtons() {
  document.querySelectorAll(".room-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".room-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedRooms = parseInt(btn.dataset.rooms);
    });
  });
}

// ─── Textarea auto-resize + keyboard ────────────────────
function setupTextarea() {
  const textarea = document.getElementById("userInput");
  const sendBtn = document.getElementById("sendBtn");

  textarea.addEventListener("input", () => {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
    sendBtn.disabled = textarea.value.trim() === "" || isStreaming;
  });

  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!sendBtn.disabled) sendMessage();
    }
  });
}

// ─── Send message ────────────────────────────────────────
function sendMessage() {
  const textarea = document.getElementById("userInput");
  const text = textarea.value.trim();
  if (!text || isStreaming) return;
  textarea.value = "";
  textarea.style.height = "auto";
  document.getElementById("sendBtn").disabled = true;
  sendMessageToAPI(text);
}

function sendQuickPrompt(text) {
  if (isStreaming) return;
  sendMessageToAPI(text);
}

async function sendMessageToAPI(text) {
  removeWelcome();
  isStreaming = true;

  appendMessage("user", text);
  conversationHistory.push({ role: "user", content: text });

  const assistantEl = appendMessage("assistant", "");
  const bubble = assistantEl.querySelector(".message-bubble");
  bubble.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';

  let fullText = "";

  try {
    const resp = await fetch(`${API_BASE}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: conversationHistory.slice(0, -1) }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    bubble.innerHTML = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.type === "text") {
            fullText += event.content;
            bubble.innerHTML = renderMarkdown(fullText);
            scrollToBottom();
          } else if (event.type === "error") {
            bubble.innerHTML = `<span style="color:var(--error)">Erreur: ${escapeHtml(event.content)}</span>`;
          }
        } catch {}
      }
    }
  } catch (e) {
    bubble.innerHTML = `<span style="color:var(--error)">Impossible de joindre l'API. ${escapeHtml(e.message)}</span>`;
  }

  if (fullText) {
    conversationHistory.push({ role: "assistant", content: fullText });
  }

  isStreaming = false;
  const textarea = document.getElementById("userInput");
  document.getElementById("sendBtn").disabled = textarea.value.trim() === "";
  scrollToBottom();
}

// ─── DOM helpers ─────────────────────────────────────────
function appendMessage(role, text) {
  const container = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = `message ${role}`;

  const avatar = role === "user" ? "👤" : "🤖";
  div.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-bubble">${text ? renderMarkdown(text) : ""}</div>
  `;

  container.appendChild(div);
  scrollToBottom();
  return div;
}

function removeWelcome() {
  const welcome = document.querySelector(".welcome-message");
  if (welcome) welcome.remove();
}

function clearMessages() {
  document.getElementById("messages").innerHTML = "";
  conversationHistory = [];
}

function clearChat() {
  document.getElementById("messages").innerHTML = `
    <div class="welcome-message">
      <div class="welcome-icon">🏠</div>
      <h2>Chat vidé</h2>
      <p>Posez une nouvelle question ou relancez l'agent depuis le panneau de gauche.</p>
    </div>
  `;
  conversationHistory = [];
}

function scrollToBottom() {
  const messages = document.getElementById("messages");
  messages.scrollTop = messages.scrollHeight;
}

// ─── Markdown renderer ───────────────────────────────────
function renderMarkdown(text) {
  let html = escapeHtml(text);

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Italic
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Links [text](url)
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // Headers
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // HR
  html = html.replace(/^---$/gm, "<hr/>");

  // Unordered lists
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>)/s, (match) => `<ul>${match}</ul>`);
  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");

  // Paragraphs (double newline)
  html = html.replace(/\n\n+/g, "</p><p>");
  html = "<p>" + html + "</p>";

  // Single newlines → <br>
  html = html.replace(/\n/g, "<br/>");

  // Clean up empty <p></p>
  html = html.replace(/<p>\s*<\/p>/g, "");

  return html;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
