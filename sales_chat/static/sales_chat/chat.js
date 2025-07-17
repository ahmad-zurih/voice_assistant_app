/* sales_chat/static/sales_chat/chat.js
   — sessions, 20‑min timer, typing indicator, coach tab, clicked logging
   — REWRITTEN to enforce a single (non‑restartable) session
   — MODIFIED to block copy/paste/cut in the textarea
*/

document.addEventListener("DOMContentLoaded", () => {
  // -------------------------------------------------------------
  // DOM shortcuts
  // -------------------------------------------------------------
  const chatForm  = document.getElementById("chat-form");
  const textarea  = document.getElementById("query");
  const sendBtn   = chatForm.querySelector("button");
  const chatBox   = document.getElementById("chat-box");

  const startBtn  = document.getElementById("start-btn");
  const endBtn    = document.getElementById("end-btn");
  const timerSpan = document.getElementById("timer");

  const coachCtr   = document.getElementById("coach-container");
  const coachTab   = document.getElementById("coach-tab");
  const coachBadge = document.getElementById("coach-badge");
  const coachPanel = document.getElementById("coach-panel");

  const csrfToken = document.querySelector('[name="csrfmiddlewaretoken"]').value;

  // -------------------------------------------------------------
  // Prevent copy/paste/cut/contextmenu in textarea
  // -------------------------------------------------------------
  ["copy", "paste", "cut"].forEach((evt) =>
    textarea.addEventListener(evt, (e) => e.preventDefault())
  );
  textarea.addEventListener("contextmenu", (e) => e.preventDefault());

  // -------------------------------------------------------------
  // persistent state helpers
  // -------------------------------------------------------------
  const sessionFinished = startBtn?.dataset?.finished === "true";

  // -------------------------------------------------------------
  // runtime state
  // -------------------------------------------------------------
  let clickSent   = true;
  let countdownId = null;
  let sessionEnd  = 0;

  // -------------------------------------------------------------
  // helper functions
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

  // coach helpers ------------------------------------------------
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

  const permanentlyHideStart = () => {
    startBtn.disabled = true;
    startBtn.classList.add("d-none");
  };

  const finishSession = async () => {
    stopCountdown();
    enableChat(false);
    permanentlyHideStart();
    endBtn.classList.add("d-none");
    resetCoachUI();

    try {
      await fetch("/chat/end/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        credentials: "same-origin",
      });
    } catch (err) {
      console.error(err);
    }

    addBubble("System", "<em>Session ended.</em>", "text-danger");
  };

  // -------------------------------------------------------------
  // early exit if the session was already finished on page load
  // -------------------------------------------------------------
  if (sessionFinished) {
    permanentlyHideStart();
    enableChat(false);
  }

  // -------------------------------------------------------------
  // start / end button handlers
  // -------------------------------------------------------------
  startBtn?.addEventListener("click", async () => {
    if (startBtn.disabled) return;

    try {
      const resp = await fetch("/chat/start/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        credentials: "same-origin",
      });

      if (resp.status === 403) {
        alert("This exercise is complete – you can’t start it again.");
        permanentlyHideStart();
        return;
      }

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
    if (textarea.disabled) return;

    enableChat(false);
    resetCoachUI();

    const userText = textarea.value.trim();
    if (!userText) {
      enableChat(true);
      return;
    }
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

    enableChat(true);

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
