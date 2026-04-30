(function () {
  const API_BASE =
    (typeof window.FAQ_CHAT_API_BASE === "string"
      ? window.FAQ_CHAT_API_BASE
      : ""
    ).replace(/\/$/, "");

  const STORAGE_SID = "faq_chat_session_id";
  const STORAGE_OPSEQ = "faq_chat_operator_seq";

  const launcher = document.getElementById("chat-launcher");
  const widget = document.getElementById("chat-widget");
  const closeBtn = document.getElementById("chat-close");
  const messagesEl = document.getElementById("chat-messages");
  const inputEl = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");

  if (!launcher || !widget || !messagesEl || !inputEl || !sendBtn) return;

  let isSending = false;
  let pollTimer = null;
  let pollInFlight = false;

  function getSessionId() {
    try {
      return sessionStorage.getItem(STORAGE_SID) || "";
    } catch (e) {
      return "";
    }
  }

  function setSessionId(sid) {
    try {
      if (sid) sessionStorage.setItem(STORAGE_SID, sid);
    } catch (e) {}
  }

  function getLastOpSeq() {
    try {
      var s = sessionStorage.getItem(STORAGE_OPSEQ);
      var n = parseInt(s, 10);
      return isNaN(n) ? 0 : n;
    } catch (e) {
      return 0;
    }
  }

  function setLastOpSeq(n) {
    try {
      sessionStorage.setItem(STORAGE_OPSEQ, String(n));
    } catch (e) {}
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(tickPoll, 2500);
    tickPoll();
  }

  function tickPoll() {
    if (pollInFlight) return;
    var sid = getSessionId();
    if (!sid) {
      stopPolling();
      return;
    }
    var after = getLastOpSeq();
    pollInFlight = true;
    fetch(
      API_BASE +
        "/api/chat/operator-poll?session_id=" +
        encodeURIComponent(sid) +
        "&after_op_seq=" +
        after
    )
      .then(function (res) {
        var ok = res.ok;
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            return { ok: ok, data: data, status: res.status };
          });
      })
      .then(function (r) {
        pollInFlight = false;
        if (!r.ok) {
          console.warn("operator-poll HTTP", r.status, r.data && r.data.detail);
          return;
        }
        var data = r.data;
        if (!data) {
          return;
        }
        var notice = data.visitor_notice;
        if (typeof notice === "string" && notice.length) {
          appendMessage(notice, "bot");
        }
        // Только явный false останавливает poll; иначе сбой парсинга/прокси не гасит long-poll.
        if (data.operator_active === false) {
          stopPolling();
          return;
        }
        if (data.operator_active !== true) {
          return;
        }
        var list = data.messages || [];
        var maxSeq = after;
        for (var i = 0; i < list.length; i++) {
          var m = list[i];
          if (m && typeof m.text === "string") {
            appendMessage(m.text, "bot");
            var seq = m.seq;
            var n = typeof seq === "number" ? seq : parseInt(seq, 10);
            if (!isNaN(n) && n > maxSeq) maxSeq = n;
          }
        }
        if (maxSeq > after) setLastOpSeq(maxSeq);
      })
      .catch(function () {
        pollInFlight = false;
      });
  }

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
      var sid = getSessionId();
      const res = await fetch(API_BASE + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: sid || undefined,
        }),
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
      var prevSid = getSessionId();
      if (data.session_id) {
        if (data.session_id !== prevSid) setLastOpSeq(0);
        setSessionId(data.session_id);
      }
      var vn = data && data.visitor_notice;
      if (typeof vn === "string" && vn.length) {
        appendMessage(vn, "bot");
      }
      const answer = (data && data.answer) || "";
      if (answer) {
        appendMessage(answer, "bot");
      } else if (!vn) {
        appendMessage("(Пустой ответ.)", "bot");
      }
      if (data.operator_active) {
        startPolling();
      } else {
        stopPolling();
      }
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
        "Привет! Я FAQ-ассистент по материалам этого сайта. Задайте вопрос об услугах, кейсах или работе с ИИ и автоматизацией — отвечу кратко. Если в базе нет ответа по теме, подключу оператора; явно попросить человека можно фразой вроде «переведи на оператора».",
        "bot"
      );
    }
    setTimeout(function () {
      inputEl.focus();
    }, 50);
    if (getSessionId()) startPolling();
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", function () {
      widget.style.display = "none";
      launcher.style.display = "flex";
      stopPolling();
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
