(function () {
  const API_BASE =
    (typeof window.FAQ_CHAT_API_BASE === "string"
      ? window.FAQ_CHAT_API_BASE
      : ""
    ).replace(/\/$/, "");

  const launcher = document.getElementById("chat-launcher");
  const widget = document.getElementById("chat-widget");
  const closeBtn = document.getElementById("chat-close");
  const messagesEl = document.getElementById("chat-messages");
  const inputEl = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");

  if (!launcher || !widget || !messagesEl || !inputEl || !sendBtn) return;

  let isSending = false;

  function appendMessage(text, from) {
    const div = document.createElement("div");
    div.className = "chat-message " + from;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendTyping() {
    const div = document.createElement("div");
    div.className = "chat-message bot";
    div.id = "faq-typing-indicator";
    div.innerHTML =
      '<div class="typing-indicator"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function removeTyping() {
    const el = document.getElementById("faq-typing-indicator");
    if (el) el.remove();
  }

  function errorDetail(data) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0] && detail[0].msg) return detail[0].msg;
    return null;
  }

  async function sendMessage() {
    if (isSending) return;
    const text = inputEl.value.trim();
    if (!text) return;

    appendMessage(text, "user");
    inputEl.value = "";

    isSending = true;
    sendBtn.disabled = true;
    appendTyping();

    try {
      const res = await fetch(API_BASE + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json().catch(function () {
        return {};
      });
      removeTyping();
      if (!res.ok) {
        const msg =
          errorDetail(data) || res.statusText || "Ошибка сервера";
        appendMessage(msg, "bot");
        return;
      }
      const answer = (data && data.answer) || "";
      appendMessage(answer || "(Пустой ответ.)", "bot");
    } catch (err) {
      console.error(err);
      removeTyping();
      appendMessage(
        "Не удалось получить ответ. Проверьте сеть и попробуйте позже.",
        "bot"
      );
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  launcher.addEventListener("click", function () {
    widget.style.display = "flex";
    launcher.style.display = "none";
    if (!messagesEl.hasChildNodes()) {
      appendMessage(
        "Привет! Я FAQ-ассистент по материалам этого сайта. Спросите об услугах, кейсах или формате работы — отвечу кратко.",
        "bot"
      );
    }
    setTimeout(function () {
      inputEl.focus();
    }, 50);
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", function () {
      widget.style.display = "none";
      launcher.style.display = "flex";
    });
  }

  sendBtn.addEventListener("click", sendMessage);

  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
})();
