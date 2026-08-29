(function () {
  "use strict";

  const DEFAULT_TIMEOUT = 22000;
  const HEALTH_DATA_TTL = 24 * 60 * 60 * 1000;
  const STORAGE_KEYS = [
    "consultDraft",
    "consultData",
    "consultAnswers",
    "consultResult",
    "emergencySymptoms",
    "emergencySignals",
    "toxinDraft",
  ];
  const CONSULT_STORAGE_KEYS = [
    "consultDraft",
    "consultData",
    "consultAnswers",
    "consultResult",
    "emergencySymptoms",
    "emergencySignals",
  ];

  const DANGER_RULES = [
    {
      id: "breathing",
      label: "明显呼吸费力、持续异常喘气，猫张口呼吸，或舌头/牙龈发紫",
      patterns: [/呼吸(困难|费力|急促)/, /喘不过气/, /张口呼吸/, /猫.{0,4}张口喘/, /(舌头|牙龈).{0,4}(发紫|灰白|苍白)/],
    },
    {
      id: "seizure",
      label: "持续抽搐、反复抽搐或无法控制的震颤",
      patterns: [/持续.{0,4}抽搐/, /反复.{0,4}抽搐/, /抽搐不止/, /癫痫持续/, /无法控制.{0,5}(发抖|震颤)/],
    },
    {
      id: "consciousness",
      label: "叫不醒、失去意识、反应极弱或突然瘫软",
      patterns: [/叫不醒/, /失去意识/, /意识(不清|异常|丧失)/, /昏迷/, /反应极弱/, /突然.{0,4}(瘫软|倒下)/],
    },
    {
      id: "mobility",
      label: "突然无法站立、无法行走或明显瘫痪",
      patterns: [/站不起来/, /无法站立/, /无法行走/, /突然.{0,4}(瘫痪|后肢无力)/],
    },
    {
      id: "bleeding",
      label: "大量出血，或持续按压仍无法止血",
      patterns: [/大量出血/, /血流不止/, /无法止血/, /止不住血/],
    },
    {
      id: "urinary",
      label: "频繁用力排尿却只有几滴，或完全尿不出来",
      patterns: [/尿不出来/, /排不出尿/, /完全无尿/, /尿闭/, /(猫砂盆|排尿).{0,10}(只有几滴|没有尿)/, /频繁.{0,8}(蹲|进).{0,6}猫砂盆.{0,8}(没尿|尿不出)/],
    },
    {
      id: "bloat",
      label: "腹部突然明显胀大，同时反复干呕但吐不出来",
      patterns: [/(腹部|肚子).{0,6}(突然|明显).{0,5}(胀大|鼓起).{0,14}(干呕|吐不出来)/, /(干呕|吐不出来).{0,14}(腹部|肚子).{0,8}(胀大|鼓起)/],
    },
    {
      id: "trauma",
      label: "车撞、高处坠落、严重咬伤或其他明显外伤",
      patterns: [/(被车撞|车祸|撞车)/, /(高处|高楼|阳台).{0,5}(坠落|掉下|摔下)/, /严重咬伤/, /异物卡喉/, /窒息/],
    },
    {
      id: "vomiting",
      label: "持续频繁呕吐或腹泻，无法留住水，或伴有血和明显虚弱",
      patterns: [/(持续|频繁|反复).{0,5}(呕吐|腹泻).{0,14}(喝水也吐|留不住水|带血|有血|明显虚弱)/, /(呕血|便血|黑便).{0,10}(虚弱|没精神|瘫软)/],
    },
    {
      id: "deteriorating",
      label: "状态正在快速恶化，或疑似中暑、中毒",
      patterns: [/快速(恶化|变差)/, /越来越严重/, /(疑似|可能|怀疑).{0,4}(中暑|中毒)/, /体温.{0,5}(过高|很高)/],
    },
  ];

  const NEGATION_PATTERN = /(没有|没有明显|未见|并无|无明显|无|不是|否认|没出现|未出现|已经排除)$/;
  let healthRequest;

  class ApiError extends Error {
    constructor(message, status = 0, code = "UNKNOWN") {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
    }
  }

  async function apiAssist(task, messages, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      options.timeoutMs || DEFAULT_TIMEOUT
    );

    try {
      const response = await fetch("/api/assist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task, messages }),
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

      if (!payload || typeof payload.result !== "object") {
        throw new ApiError("没有收到有效回复，请重新尝试。", response.status, "EMPTY_RESPONSE");
      }
      return payload.result;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error?.name === "AbortError") {
        throw new ApiError("等待时间过长，已切换到本地安全提示。", 0, "TIMEOUT");
      }
      throw new ApiError("暂时无法连接 AI 服务，已保留本地安全提示。", 0, "NETWORK_ERROR");
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function getServiceHealth() {
    if (!healthRequest) {
      healthRequest = fetch("/api/health", { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : Promise.reject(new Error("health"))))
        .catch(() => ({ status: "offline", configured: false }));
    }
    return healthRequest;
  }

  async function bindServiceStatus() {
    const nodes = Array.from(document.querySelectorAll("[data-service-status]"));
    if (!nodes.length) return;

    const health = await getServiceHealth();
    nodes.forEach((node) => {
      const configured = Boolean(health.configured ?? health.modelConfigured);
      node.classList.toggle("is-online", configured);
      node.classList.toggle("is-local", !configured);
      const label = node.querySelector("[data-service-label]") || node;
      label.textContent = configured ? "AI 辅助已配置" : "本地安全规则已就绪";
      node.title = configured
        ? "模型已配置；危险信号仍由本地规则优先处理"
        : "未连接模型时，紧急分流与固定安全提示仍可使用";
    });
  }

  function appendMessage(container, text, type = "ai", id = "", shouldScroll = true) {
    const node = document.createElement("div");
    node.className = `message ${type}`;
    if (id) node.id = id;
    node.textContent = text;
    container.appendChild(node);
    if (shouldScroll) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return node;
  }

  function showInlineError(container, message, retry) {
    const box = document.createElement("div");
    box.className = "error-state";
    box.setAttribute("role", "alert");

    const text = document.createElement("span");
    text.textContent = message;
    box.appendChild(text);

    if (typeof retry === "function") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-button";
      button.textContent = "重新尝试";
      button.addEventListener("click", () => {
        box.remove();
        retry();
      });
      box.appendChild(button);
    }

    container.appendChild(box);
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return box;
  }

  function getStoredJson(key, fallback = null) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      if (parsed && parsed.__miguEnvelope === 1) {
        if (parsed.expiresAt && Date.now() > parsed.expiresAt) {
          localStorage.removeItem(key);
          return fallback;
        }
        return parsed.value ?? fallback;
      }
      if (STORAGE_KEYS.includes(key)) setStoredJson(key, parsed);
      return parsed;
    } catch {
      return fallback;
    }
  }

  function setStoredJson(key, value, ttlMs = HEALTH_DATA_TTL) {
    try {
      const envelope = {
        __miguEnvelope: 1,
        expiresAt: ttlMs > 0 ? Date.now() + ttlMs : null,
        value,
      };
      localStorage.setItem(key, JSON.stringify(envelope));
      return true;
    } catch {
      return false;
    }
  }

  function removeStoredJson(key) {
    try {
      localStorage.removeItem(key);
      return true;
    } catch {
      return false;
    }
  }

  function clearConsultData() {
    let cleared = true;
    CONSULT_STORAGE_KEYS.forEach((key) => {
      if (!removeStoredJson(key)) cleared = false;
    });
    return cleared;
  }

  function clearHealthData() {
    let cleared = true;
    STORAGE_KEYS.forEach((key) => {
      if (!removeStoredJson(key)) cleared = false;
    });
    return cleared;
  }

  function wireClearButtons() {
    document.querySelectorAll("[data-clear-health]").forEach((button) => {
      button.addEventListener("click", () => {
        const cleared = clearHealthData();
        const original = button.textContent;
        button.textContent = cleared ? "本机记录已清除" : "当前浏览器无法清除记录";
        button.disabled = true;
        window.setTimeout(() => {
          button.textContent = original;
          button.disabled = false;
        }, 1800);
      });
    });
  }

  function isNegated(text, matchIndex) {
    const prefix = text.slice(Math.max(0, matchIndex - 10), matchIndex).replace(/[，。；、\s]/g, "");
    return NEGATION_PATTERN.test(prefix);
  }

  function detectDangerSignals(value) {
    const text = String(value || "").trim();
    if (!text) return [];

    return DANGER_RULES.filter((rule) =>
      rule.patterns.some((pattern) => {
        const flags = pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`;
        const matcher = new RegExp(pattern.source, flags);
        let match;
        while ((match = matcher.exec(text)) !== null) {
          if (!isNegated(text, match.index)) return true;
          if (match[0] === "") matcher.lastIndex += 1;
        }
        return false;
      })
    ).map((rule) => ({ id: rule.id, label: rule.label }));
  }

  function storeEmergencySignals(signals) {
    const labels = (signals || []).map((signal) =>
      typeof signal === "string" ? signal : signal.label
    );
    setStoredJson("emergencySymptoms", labels);
  }

  function valueOrUnknown(value) {
    if (value === 0 || value === "0") return "0";
    return String(value || "不确定").trim() || "不确定";
  }

  function buildConsultSummary(data, answers = []) {
    const lines = [
      "咪咕医生 · 就诊沟通摘要",
      `生成时间：${formatDateTime(new Date())}`,
      "",
      `宠物：${valueOrUnknown(data.petType)}｜品种：${valueOrUnknown(data.petBreed)}`,
      `年龄：${valueOrUnknown(data.petAge)}${data.petAge && data.petAgeUnit ? data.petAgeUnit : ""}｜体重：${data.petWeight ? `${data.petWeight} kg` : "不确定"}`,
      `性别：${valueOrUnknown(data.petGender)}｜绝育：${valueOrUnknown(data.petNeutered)}`,
      `基础疾病或过敏史：${valueOrUnknown(data.petHistory)}`,
      "",
      `主要症状：${valueOrUnknown(data.symptom)}`,
      `开始时间：${valueOrUnknown(data.duration)}｜变化趋势：${valueOrUnknown(data.trend)}`,
      `进食：${valueOrUnknown(data.eating)}｜饮水：${valueOrUnknown(data.drinking)}`,
      `排尿：${valueOrUnknown(data.urination)}｜排便：${valueOrUnknown(data.defecation)}`,
      `发生频率：${valueOrUnknown(data.frequency)}`,
      `其他异常：${valueOrUnknown(data.other)}`,
      `近期特殊情况：${valueOrUnknown(data.recent)}`,
    ];

    if (Array.isArray(answers) && answers.length) {
      lines.push("", "补充问答：");
      answers.forEach((item, index) => {
        lines.push(`${index + 1}. ${valueOrUnknown(item.question)}`);
        lines.push(`   回答：${valueOrUnknown(item.answer)}`);
      });
    }

    lines.push("", "说明：以上为宠物主人填写与系统整理的信息，不是诊断或处方。");
    return lines.join("\n");
  }

  function buildToxinSummary(data) {
    return [
      "咪咕医生 · 误食沟通摘要",
      `生成时间：${formatDateTime(new Date())}`,
      "",
      `宠物：${valueOrUnknown(data.petType)}｜体重：${data.petWeight ? `${data.petWeight} kg` : "不确定"}`,
      `疑似误食：${valueOrUnknown(data.toxin)}`,
      `估计剂量：${data.amountUnknown ? "不确定" : `${valueOrUnknown(data.amount)}${valueOrUnknown(data.amountUnit)}`}`,
      `距误食时间：${data.timeUnknown ? "不确定" : `${valueOrUnknown(data.time)}${valueOrUnknown(data.timeUnit)}`}`,
      `当前症状或补充：${valueOrUnknown(data.symptoms)}`,
      "",
      "已提醒：不要自行催吐、用药或强行喂食喂水；请带上包装或成分照片联系执业兽医。",
    ].join("\n");
  }

  function formatDateTime(date) {
    try {
      return new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(date);
    } catch {
      return date.toLocaleString();
    }
  }

  async function copyText(text) {
    const value = String(text || "");
    if (!value) return false;
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      }
      textarea.remove();
      return copied;
    }
  }

  function byId(id) {
    return document.getElementById(id);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindServiceStatus();
    wireClearButtons();
  });

  window.MiguApp = {
    ApiError,
    apiAssist,
    appendMessage,
    bindServiceStatus,
    buildConsultSummary,
    buildToxinSummary,
    byId,
    clearConsultData,
    clearHealthData,
    copyText,
    detectDangerSignals,
    formatDateTime,
    getServiceHealth,
    getStoredJson,
    removeStoredJson,
    setStoredJson,
    showInlineError,
    storeEmergencySignals,
    valueOrUnknown,
  };
})();
