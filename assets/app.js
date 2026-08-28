(function () {
  const DEFAULT_TIMEOUT = 24000;

  class ApiError extends Error {
    constructor(message, status = 0, code = "UNKNOWN") {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
    }
  }

  async function apiChat(messages, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      options.timeoutMs || DEFAULT_TIMEOUT
    );

    try {
      const response = await fetch("/api/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: "deepseek-chat", messages }),
        signal: controller.signal,
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new ApiError(
          payload.error || "服务暂时不可用，请稍后重试。",
          response.status,
          payload.code || "HTTP_ERROR"
        );
      }

      const content = payload?.choices?.[0]?.message?.content;
      if (typeof content !== "string" || !content.trim()) {
        throw new ApiError("没有收到有效回复，请重新尝试。", response.status, "EMPTY_RESPONSE");
      }
      return content.trim();
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error?.name === "AbortError") {
        throw new ApiError("请求超时了，请检查网络后重试。", 0, "TIMEOUT");
      }
      throw new ApiError("无法连接到本地服务，请确认后端已启动。", 0, "NETWORK_ERROR");
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function appendMessage(container, text, type = "ai", id = "") {
    const node = document.createElement("div");
    node.className = `message ${type}`;
    if (id) node.id = id;
    node.textContent = text;
    container.appendChild(node);
    node.scrollIntoView({ block: "end", behavior: "smooth" });
    return node;
  }

  function showInlineError(container, message, retry) {
    const box = document.createElement("div");
    box.className = "error-state";

    const text = document.createElement("span");
    text.textContent = message;
    box.appendChild(text);

    if (typeof retry === "function") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button-secondary";
      button.style.marginTop = "10px";
      button.textContent = "重新尝试";
      button.addEventListener("click", () => {
        box.remove();
        retry();
      });
      box.appendChild(button);
    }

    container.appendChild(box);
    box.scrollIntoView({ block: "end", behavior: "smooth" });
    return box;
  }

  function getStoredJson(key, fallback = null) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }

  function setStoredJson(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  function byId(id) {
    return document.getElementById(id);
  }

  window.MiguApp = {
    ApiError,
    apiChat,
    appendMessage,
    showInlineError,
    getStoredJson,
    setStoredJson,
    byId,
  };
})();
