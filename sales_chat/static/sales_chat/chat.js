/* sales_chat/static/sales_chat/chat.js
   — no-stream version with human-style “typing…” indicator
*/

document.addEventListener("DOMContentLoaded", () => {
  // -------------------------------------------------------------
  // DOM shortcuts
  // -------------------------------------------------------------
  const chatForm  = document.getElementById("chat-form");
  const chatBox   = document.getElementById("chat-box");
  const coachBox  = document.getElementById("coach-box");
  const csrfToken = document.querySelector('[name="csrfmiddlewaretoken"]').value;

  // -------------------------------------------------------------
  // helpers
  // -------------------------------------------------------------
  /** keep a scrollable element pinned to the bottom */
  const scrollToBottom = (el) => {
    el.scrollTop = el.scrollHeight;
  };

  /** insert a bubble; returns the created element */
  const addBubble = (who, htmlText, extraCls = "") => {
    chatBox.insertAdjacentHTML(
      "beforeend",
      `<div class="mb-2 ${extraCls}"><strong>${who}:</strong> ${htmlText}</div>`
    );
    scrollToBottom(chatBox);
    return chatBox.lastElementChild;
  };

  /** append advice to the sidebar */
  const addAdvice = (advice) => {
    coachBox.insertAdjacentHTML(
      "beforeend",
      `<div class="mb-2"><strong>Coach:</strong> ${advice}</div>`
    );
    scrollToBottom(coachBox);
  };

  // -------------------------------------------------------------
  // main submit handler
  // -------------------------------------------------------------
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const textarea = document.getElementById("query");
    const userText = textarea.value.trim();
    if (!userText) return;

    // show the salesperson’s message
    addBubble("You", userText);
    textarea.value = "";

    // placeholder while AI “types”
    const typingElem = addBubble(
      "Customer",
      "<em>is typing…</em>",
      "text-muted fst-italic"
    );

    // build POST body
    const formData = new FormData();
    formData.append("query", userText);
    formData.append("csrfmiddlewaretoken", csrfToken);

    // ---------------- customer AI call ----------------
    try {
      const resp = await fetch("/chat/stream/", {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });

      if (!resp.ok) {
        // fallback for non-200 errors
        throw new Error(`status ${resp.status}`);
      }

      const data = await resp.json();           // ← parses {"answer": "..."}
      const answer = data.answer || "[empty]";

      // replace “typing…” with the real text
      typingElem.classList.remove("text-muted", "fst-italic");
      typingElem.innerHTML = `<strong>Customer:</strong> ${answer}`;
    } catch (err) {
      typingElem.innerHTML =
        `<span class="text-danger">[error: ${err.message}]</span>`;
      console.error(err);
    }

    // ---------------- coach advice (unchanged) --------
    try {
      // a short pause so the server can close the previous request cleanly
      await new Promise((r) => setTimeout(r, 400));

      const coachResp = await fetch("/chat/coach/", {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
          Accept: "application/json",
        },
        credentials: "same-origin",
      });

      const { advice } = await coachResp.json();
      addAdvice(advice || "[no response]");
    } catch (err) {
      addAdvice("<span class='text-danger'>error getting advice</span>");
      console.error(err);
    }
  });
});
