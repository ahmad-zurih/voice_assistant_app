/* sales_chat/static/sales_chat/chat.js
   — no-stream version with typing indicator + hidden coach tab
*/

document.addEventListener("DOMContentLoaded", () => {
  // -------------------------------------------------------------
  // DOM shortcuts
  // -------------------------------------------------------------
  const chatForm   = document.getElementById("chat-form");
  const chatBox    = document.getElementById("chat-box");

  // coach UI elements
  const coachCtr   = document.getElementById("coach-container");
  const coachTab   = document.getElementById("coach-tab");
  const coachBadge = document.getElementById("coach-badge");
  const coachPanel = document.getElementById("coach-panel");

  const csrfToken  = document.querySelector('[name="csrfmiddlewaretoken"]').value;

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

  // coach helpers ------------------------------------------------
  const resetCoachUI = () => {
    coachPanel.style.display = "none";
    coachCtr.classList.add("d-none");
    coachBadge.textContent = "";
  };

  const showCoachAdvice = (advice) => {
    if (!advice) return;                      // nothing to show

    coachPanel.innerHTML = advice.replace(/\n/g, "<br>");
    coachCtr.classList.remove("d-none");
    coachBadge.textContent = "1";             // unread marker
  };

  // click toggles panel & clears unread
  coachTab.addEventListener("click", () => {
    const open = coachPanel.style.display === "block";
    coachPanel.style.display = open ? "none" : "block";
    if (!open) coachBadge.textContent = "";   // mark as read
  });

  // -------------------------------------------------------------
  // main submit handler
  // -------------------------------------------------------------
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    // 🔄 clear any previous (read *or* unread) advice
    resetCoachUI();

    const textarea = document.getElementById("query");
    const userText = textarea.value.trim();
    if (!userText) return;

    addBubble("You", userText);
    textarea.value = "";

    // --- customer typing placeholder ---------------------------
    const typingElem = addBubble(
      "Customer",
      "<em>is typing…</em>",
      "text-muted fst-italic"
    );

    const formData = new FormData();
    formData.append("query", userText);
    formData.append("csrfmiddlewaretoken", csrfToken);

    // ---------------- customer AI call -------------------------
    try {
      const resp = await fetch("/chat/stream/", {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });

      if (!resp.ok) throw new Error(`status ${resp.status}`);

      const { answer } = await resp.json();
      typingElem.classList.remove("text-muted", "fst-italic");
      typingElem.innerHTML = `<strong>Customer:</strong> ${answer || "[empty]"}`;
    } catch (err) {
      typingElem.innerHTML =
        `<span class="text-danger">[error: ${err.message}]</span>`;
      console.error(err);
    }

    // ---------------- coach advice fetch -----------------------
    try {
      await new Promise((r) => setTimeout(r, 400));   // let server finish
      const coachResp = await fetch("/chat/coach/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
        credentials: "same-origin",
      });

      const { advice } = await coachResp.json();
      showCoachAdvice(advice);        // only shows if non-empty
    } catch (err) {
      console.error("coach error:", err);
      // silent fail → no popup
    }
  });
});
