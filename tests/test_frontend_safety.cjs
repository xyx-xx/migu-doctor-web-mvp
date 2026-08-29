const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadApp() {
  const storage = new Map();
  const sandbox = {
    AbortController,
    Date,
    Intl,
    URLSearchParams,
    clearTimeout,
    console,
    fetch: async () => { throw new Error("fetch is not used in these tests"); },
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      removeItem: (key) => storage.delete(key),
      setItem: (key, value) => storage.set(key, String(value)),
    },
    navigator: {},
    setTimeout,
  };
  sandbox.window = sandbox;
  sandbox.document = {
    addEventListener() {},
    getElementById() { return null; },
    querySelectorAll() { return []; },
  };

  const appPath = path.join(__dirname, "..", "assets", "app.js");
  vm.runInNewContext(fs.readFileSync(appPath, "utf8"), sandbox, { filename: appPath });
  return sandbox.MiguApp;
}

const app = loadApp();

function ids(text) {
  return app.detectDangerSignals(text).map((signal) => signal.id);
}

test("明确否定的危险信号不会误触发", () => {
  assert.equal(ids("没有呼吸费力，精神和活动量正常").length, 0);
  assert.equal(ids("未出现抽搐，也没有大量出血").length, 0);
  assert.equal(ids("不是完全无尿，今天排尿正常").length, 0);
});

test("同一句里后续出现的真实危险信号不会被前面的否定掩盖", () => {
  assert.ok(ids("一开始没有呼吸困难，但现在呼吸费力").includes("breathing"));
  assert.ok(ids("之前没有抽搐，刚才开始反复抽搐").includes("seizure"));
});

test("关键危险信号可以被确定性规则识别", () => {
  assert.ok(ids("公猫频繁蹲猫砂盆但完全尿不出来").includes("urinary"));
  assert.ok(ids("肚子突然胀大，反复干呕但吐不出来").includes("bloat"));
  assert.ok(ids("被车撞后突然站不起来").includes("trauma"));
  assert.ok(ids("状态越来越严重").includes("deteriorating"));
});

test("病例级 AI 授权会被保存，并在聊天页再次核对", () => {
  const consult = fs.readFileSync(path.join(__dirname, "..", "consult.html"), "utf8");
  const chat = fs.readFileSync(path.join(__dirname, "..", "chat.html"), "utf8");

  assert.match(consult, /aiProcessingAuthorized:\s*aiConfigured\s*&&\s*data\.aiConsent/);
  assert.match(consult, /processingMode:\s*aiConfigured\s*&&\s*data\.aiConsent\s*\?\s*"ai-authorized"\s*:\s*"local-only"/);
  assert.match(chat, /consultData\.aiProcessingAuthorized\s*===\s*true/);
  assert.match(chat, /consultData\.processingMode\s*===\s*"ai-authorized"/);
  assert.match(chat, /if\s*\(!aiProcessingAllowed\)\s*\{\s*showQuestionForm\(fallbackQuestions,\s*true\)/);
});
