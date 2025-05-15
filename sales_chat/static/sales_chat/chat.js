/* sales_chat/static/sales_chat/chat.js
   — sessions, 20-min timer, typing indicator, coach tab, clicked logging
*/

document.addEventListener("DOMContentLoaded", () => {
  // -------------------------------------------------------------
  // DOM shortcuts
  // -------------------------------------------------------------
  const chatForm   = document.getElementById("chat-form");
  const textarea   = document.getElementById("query");
  const sendBtn    = chatForm.querySelector("button");
  const chatBox    = document.getElementById("chat-box");

  const startBtn   = document.getElementById("start-btn");
  const endBtn     = document.getElementById("end-btn");
  const timerSpan  = document.getElementById("timer");

  const coachCtr   = document.getElementById("coach-container");
  const coachTab   = document.getElementById("coach-tab");
  const coachBadge = document.getElementById("coach-badge");
  const coachPanel = document.getElementById("coach-panel");

  const csrfToken  = document.querySelector('[name="csrfmiddlewaretoken"]').value;

  // -------------------------------------------------------------
  // state
  // -------------------------------------------------------------
  let clickSent   = true;      // starts true (nothing to click yet)
  let countdownId = null;      // setInterval handle
  let sessionEnd  = 0;         // timestamp when session should end

  // -------------------------------------------------------------
  // helpers
  // -------------------------------------------------------------
  const scrollToBottom = (el) => { el.scrollTop = el.scrollHeight; };

  const addBubble = (who, htmlText, extraCls = "") => {
    chatBox.insertAdjacentHTML(
      "beforeend",
      `<div class="mb-2 ${extraCls}"><strong>${who}:</strong> ${htmlText}</div>`
    );
    scrollToBottom(chatBox);
    return chatBox.lastElementChild;
  };

  // coach helpers -----------------------------------------------
  const resetCoachUI = () => {
    coachPanel.style.display = "none";
    coachCtr.classList.add("d-none");
    coachBadge.textContent = "";
    clickSent = true;
  };

  const showCoachAdvice = (advice) => {
    if (!advice) return;
    coachPanel.innerHTML = advice.replace(/\n/g, "<br>");
    coachCtr.classList.remove("d-none");
    coachBadge.textContent = "1";
    clickSent = false;
  };

  // -------------------------------------------------------------
  // session timer
  // -------------------------------------------------------------
  const tick = () => {
    const remaining = Math.max(0, Math.floor((sessionEnd - Date.now()) / 1000));
    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    timerSpan.textContent = `${m}:${s}`;
    if (remaining === 0) finishSession();
  };

  const startCountdown = (durationSeconds) => {
    sessionEnd = Date.now() + durationSeconds * 1000;
    tick();
    countdownId = setInterval(tick, 1000);
  };

  const stopCountdown = () => {
    clearInterval(countdownId);
    timerSpan.textContent = "";
  };

  // -------------------------------------------------------------
  // UI enable / disable helpers
  // -------------------------------------------------------------
  const enableChat = (enabled) => {
    textarea.disabled = sendBtn.disabled = !enabled;
  };

  const finishSession = async () => {
    stopCountdown();
    enableChat(false);
    startBtn.classList.remove("d-none");
    endBtn.classList.add("d-none");
    resetCoachUI();
    await fetch("/chat/end/", {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken },
      credentials: "same-origin",
    }).catch(console.error);
    addBubble("System", "<em>Session ended.</em>", "text-danger");
  };

  // -------------------------------------------------------------
  // start / end button handlers
  // -------------------------------------------------------------
  startBtn.addEventListener("click", async () => {
    try {
      const resp = await fetch("/chat/start/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        credentials: "same-origin",
      });
      if (!resp.ok) throw new Error(resp.status);
      const { duration } = await resp.json();
      enableChat(true);
      startBtn.classList.add("d-none");
      endBtn.classList.remove("d-none");
      startCountdown(duration);
    } catch (err) {
      alert("Could not start session.");
      console.error(err);
    }
  });

  endBtn.addEventListener("click", finishSession);

  // -------------------------------------------------------------
  // coach tab click → mark as read
  // -------------------------------------------------------------
  coachTab.addEventListener("click", () => {
    const open = coachPanel.style.display === "block";
    coachPanel.style.display = open ? "none" : "block";
    if (!open) {
      coachBadge.textContent = "";
      if (!clickSent) {
        fetch("/chat/coach/clicked/", {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          credentials: "same-origin",
        }).catch(console.error);
        clickSent = true;
      }
    }
  });

  // -------------------------------------------------------------
  // main submit handler
  // -------------------------------------------------------------
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (textarea.disabled) return;     // should never happen

    resetCoachUI();

    const userText = textarea.value.trim();
    if (!userText) return;
    textarea.value = "";

    addBubble("You", userText);

    const typingElem = addBubble(
      "Customer",
      '<em class="typing-indicator typing-dots">is typing…</em>'
    );

    const formData = new FormData();
    formData.append("query", userText);
    formData.append("csrfmiddlewaretoken", csrfToken);

    try {
      const resp = await fetch("/chat/stream/", {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (resp.status === 403) { finishSession(); return; }
      if (!resp.ok) throw new Error(resp.status);

      const { answer } = await resp.json();
      typingElem.innerHTML = `<strong>Customer:</strong> ${answer || "[empty]"}`;
    } catch (err) {
      typingElem.innerHTML = `<span class="text-danger">[error]</span>`;
      console.error(err);
    }

    // --- coach advice ------------------------------------------
    try {
      await new Promise((r) => setTimeout(r, 400));
      const coachResp = await fetch("/chat/coach/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
        credentials: "same-origin",
      });
      if (coachResp.status === 403) { finishSession(); return; }

      const { advice } = await coachResp.json();
      showCoachAdvice(advice);
    } catch (err) {
      console.error("coach error:", err);
    }
  });
});
