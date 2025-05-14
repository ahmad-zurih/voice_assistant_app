/* sales_chat/static/sales_chat/chat.js – FULL SCRIPT */

// run after DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  const chatForm  = document.getElementById("chat-form");
  const chatBox   = document.getElementById("chat-box");
  const coachBox  = document.getElementById("coach-box");
  const csrfToken = document.querySelector('[name="csrfmiddlewaretoken"]').value;

  /** helper to keep a scrollable element pinned to the bottom */
  const scrollToBottom = (el) => {
    el.scrollTop = el.scrollHeight;
  };

  /** append a bubble to the main chat */
  const addBubble = (who, text) => {
    chatBox.insertAdjacentHTML(
      "beforeend",
      `<div class="mb-2"><strong>${who}:</strong> ${text}</div>`
    );
    scrollToBottom(chatBox);
  };

  /** append advice to the sidebar */
  const addAdvice = (advice) => {
    coachBox.insertAdjacentHTML(
      "beforeend",
      `<div class="mb-2"><strong>Coach:</strong> ${advice}</div>`
    );
    scrollToBottom(coachBox);
  };

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const textarea = document.getElementById("query");
    const userText = textarea.value.trim();
    if (!userText) return;

    // show user message
    addBubble("You", userText);
    textarea.value = "";

    // holder for streamed customer reply
    const botElem = document.createElement("div");
    botElem.innerHTML = "<strong>Customer:</strong> ";
    chatBox.appendChild(botElem);
    scrollToBottom(chatBox);

    // ---- stream customer response ----
    const formData = new FormData();
    formData.append("query", userText);
    formData.append("csrfmiddlewaretoken", csrfToken);

    try {
      const resp = await fetch("/chat/stream/", {
      method: "POST",
      body: formData,
      credentials: "same-origin" // ensure session cookie travels with the request
    });

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let done = false;

      while (!done) {
        const { value, done: rdrDone } = await reader.read();
        if (value) botElem.innerHTML += decoder.decode(value, { stream: true });
        done = rdrDone;
        scrollToBottom(chatBox);
      }
    } catch (err) {
      botElem.innerHTML += `<span class="text-danger">[error: ${err.message}]</span>`;
      console.error(err);
    }

    // ---- fetch coach advice (always append) ----
    try {
      // wait a short moment to make sure the server closed the streaming request
      await new Promise(r => setTimeout(r, 400));

      const coachResp = await fetch("/chat/coach/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken, "Accept": "application/json" },
        credentials: "same-origin",
      });

      const { advice } = await coachResp.json();
      // even if empty string, addAdvice shows why
      addAdvice(advice || "[no response]");
      console.log("Coach advice:", advice);
    } catch (err) {
      addAdvice(`<span class='text-danger'>error getting advice</span>`);
      console.error(err);
    }
  });
});
