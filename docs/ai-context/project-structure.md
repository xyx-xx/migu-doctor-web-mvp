# 咪咕医生项目结构

## 目录树

```text
migu-doctor-web-mvp/
├── index.html                    # 首页、三条主路径、紧急入口与安全说明
├── consult.html                  # 三步症状风险分流表单
├── chat.html                     # AI 追问、三段行动结果与就诊沟通卡
├── toxin.html                    # 完全确定性的误食分流与沟通摘要
├── wiki.html                     # 日常健康百科与本地科普兜底
├── emergency.html                # 不使用 AI 的紧急行动页
├── favicon.svg                   # 共用品牌图标
│
├── assets/
│   ├── styles.css                # 品牌、响应式布局、表单、结果与无障碍样式
│   ├── app.js                    # API、本地存储、危险规则、摘要和复制工具
│   └── pets-warm-v1.jpg          # 首页暖色手绘猫狗主视觉（600×900）
│
├── api_proxy.py                  # 固定静态服务、/api/assist 和 /api/health
├── request_validation.py         # 请求、结构化结果和危险建议校验
├── prompts.py                    # 四类服务端系统提示词
├── requirements.txt              # openai 与 python-dotenv
├── .env.example                  # 项目本地环境变量模板，不含真实密钥
├── .gitignore                    # 密钥、缓存、虚拟环境与历史 app.py 排除
│
├── tests/
│   ├── test_api_proxy.py         # 22 项请求、静态服务和输出安全测试
│   ├── test_frontend_safety.cjs  # 3 项前端危险信号与否定语义测试
│   └── test_static_pages.py      # 2 项页面资源与 viewport 测试
│
├── README.md                     # 对外项目说明、运行方法与限制
├── CLAUDE.md                     # AI 协作入口和长期安全规则
├── docs/
│   └── ai-context/
│       ├── spec.md               # 当前产品规格与验收边界
│       ├── progress.md           # 已完成、限制与下一阶段
│       └── project-structure.md  # 本文件
│
├── .claude/
│   ├── settings.json
│   ├── commands/
│   │   └── prime.md
│   ├── hooks/
│   │   ├── security-scan.sh
│   │   └── config/
│   │       ├── pipeline.json
│   │       └── sensitive-patterns.json
│   └── skills/
│       └── update-docs/
│           └── SKILL.md
│
├── home.png                     # 保留的历史视觉参考，不对浏览器发布
├── consult.png                  # 保留的历史视觉参考，不对浏览器发布
├── chat.png                     # 保留的历史视觉参考，不对浏览器发布
├── wiki.png                     # 保留的历史视觉参考，不对浏览器发布
└── emergency.png                # 保留的历史视觉参考，不对浏览器发布
```

本机可能仍存在被 `.gitignore` 排除的早期 Streamlit `app.py`。它不是当前 Web 产品入口、不纳入版本控制，也不在静态白名单中。当前唯一后端入口是 `api_proxy.py`。

## 页面职责

| 页面 | 确定性逻辑 | AI 任务 | 主要输出 |
| --- | --- | --- | --- |
| `index.html` | 紧急入口、服务状态、本机数据清除 | 无 | 路径选择与产品边界 |
| `consult.html` | 危险信号、字段校验、三步进度、风险前置跳转 | 无 | 病例资料 |
| `chat.html` | 本地风险最低线、危险关键词、失败兜底 | `triage_questions`、`triage_result`、`triage_followup` | 三段结果和就诊沟通卡 |
| `toxin.html` | 全部误食分流、输入边界和行动结果 | 无 | 联系兽医/立即就医和误食摘要 |
| `wiki.html` | 误食/危险路由、本地科普卡 | `wiki` | 日常养护说明 |
| `emergency.html` | 显示危险信号和固定行动步骤 | 无 | 医院沟通与转运准备 |

## 共用前端模块

`assets/app.js` 提供：

- `apiAssist(task, messages)`：统一调用 `/api/assist`；
- `getServiceHealth()`：读取本地配置状态，不执行上游探活；
- `getStoredJson()` / `setStoredJson()`：带 24 小时过期时间的 `localStorage` 封装；
- `clearConsultData()`：只清除症状问诊、结果和相关危险信号，保留误食草稿；
- `clearHealthData()`：清除当前浏览器健康相关记录；
- `detectDangerSignals()`：带基本否定词判断的危险信号规则；
- `storeEmergencySignals()`：把危险信号交给紧急页；
- `buildConsultSummary()`：生成症状就诊沟通摘要；
- `buildToxinSummary()`：生成误食沟通摘要；
- `copyText()`：Clipboard API 与兼容回退；
- 纯文本消息、错误卡、日期与 DOM 工具。

页面脚本使用 `textContent` 构建动态内容，不把模型输出写入 `innerHTML`。

## 本地数据

```text
localStorage
├── consultDraft       # 症状表单草稿
├── consultData        # 已提交病例，含处理模式、AI 授权状态与授权时间
├── consultAnswers     # AI 追问及主人回答
├── consultResult      # 与病例 createdAt 绑定的已生成风险结果
├── emergencySymptoms # 当前危险信号
└── toxinDraft         # 误食表单草稿
```

新写入值结构：

```json
{
  "__miguEnvelope": 1,
  "expiresAt": 1787912345678,
  "value": {}
}
```

默认有效期为 24 小时。读取到过期值时会删除；页面也提供主动清除入口。聊天页会再次核对病例创建时保存的处理模式与 AI 授权，旧病例或本地模式病例不会因后来配置模型而自动外发。当前没有服务端病例存储。

## API 请求流

```text
chat.html / wiki.html
       │
       │ { task, messages }
       ▼
assets/app.js::apiAssist
       │ POST /api/assist
       ▼
api_proxy.py
├─ request_validation.validate_assist_request
├─ prompts.get_system_prompt
├─ DeepSeek deepseek-v4-flash（thinking disabled）
├─ request_validation.parse/validate model output
├─ dangerous-advice filter
└─ { task, result, model } 或 { error, code }
```

`toxin.html` 和 `emergency.html` 不进入这条 AI 请求流。

## `/api/assist` 契约

请求正文只能包含：

```json
{
  "task": "wiki",
  "messages": [
    {
      "role": "user",
      "content": "成猫日常饮水怎么观察？"
    }
  ]
}
```

约束：

- task：`triage_questions`、`triage_result`、`triage_followup`、`wiki`；
- role：仅 `user`、`assistant`；
- 最后一条消息必须是 `user`；
- 每条消息只能含 `role`、`content`；
- 最多 24 条消息；
- 单条最多 6,000 字符；
- 合计最多 28,000 字符；
- HTTP 正文最多 64 KiB；
- 浏览器不能传模型、系统提示词或其他控制字段。

成功结果：

```text
triage_questions → result.questions: string[2..3]
triage_result    → result:
  risk: OBSERVE_WITH_GUARDRAILS | CONTACT_VET_NOW | EMERGENCY_NOW
  riskLabel: string
  rationale: string
  actions: string[]
  emergencySigns: string[]
triage_followup  → result.text: string
wiki             → result.text: string
```

## 后端文件职责

### `api_proxy.py`

- 只监听 `127.0.0.1`；
- 从项目目录显式加载 `.env`；
- 默认模型 `deepseek-v4-flash`；
- 支持服务端 `DEEPSEEK_MODEL` 覆盖；
- 为每个 task 注入服务端提示词；
- 调用模型时显式关闭 thinking；
- 对结构/安全失败返回固定任务兜底；
- 保持 `{error, code}` 的上游错误协议；
- 提供不做外部探活的 `/api/health`。

### `request_validation.py`

- 严格校验 task、消息角色、字段、数量与长度；
- 解析模型 JSON，拒绝重复键和非法常量；
- 校验问题数组和三段结果；
- 规范化风险标签；
- 检测催吐、双氧水/盐水、刺激咽喉、强行喂食和处方式剂量等危险建议。

### `prompts.py`

服务端独占四类系统提示词：

- `triage_questions`
- `triage_result`
- `triage_followup`
- `wiki`

用户和 assistant 历史均被视为不可信病例资料，不能覆盖系统安全规则。

## 静态发布白名单

允许 GET/HEAD：

```text
/
/index.html
/consult.html
/chat.html
/wiki.html
/emergency.html
/toxin.html
/favicon.svg
/assets/app.js
/assets/pets-warm-v1.jpg
/assets/styles.css
```

其余静态路径一律 404。尤其禁止：

- `.env`、`.env.example`；
- `.git/`；
- `api_proxy.py`、`request_validation.py`、`prompts.py`；
- `tests/`、`docs/`、`.claude/`；
- 历史 `app.py`；
- `assets/` 目录列表和任何未列入的文件。

静态根固定为脚本目录，因此从父目录或其他 cwd 启动不会发布错误目录。

## 测试结构

`tests/test_api_proxy.py` 共 22 项，覆盖：

- 请求角色、task、额外字段和长度；
- 三段风险与危险建议识别；
- 任意 cwd 的固定静态根；
- GET/HEAD 白名单和敏感路径；
- health、旧接口移除和 MIME；
- 模型名、thinking、服务端系统提示词；
- 合法/非法结构化结果；
- 固定安全兜底和上游错误。

`tests/test_static_pages.py` 共 2 项，覆盖：

- 六个页面引用的本地文件存在；
- 六个页面声明移动端 viewport。

`tests/test_frontend_safety.cjs` 共 3 项，覆盖危险信号识别和否定语义。

合计 28 项（Python 24 项 + Node 4 项）。

## 环境与启动

`.env.example`：

```env
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
PORT=8000
```

`.env` 必须位于项目目录，并由 Git 忽略。启动命令：

```bash
python api_proxy.py
```

静态资源和确定性流程不依赖 API Key。未配置密钥时，AI 任务由页面本地兜底接管。

## 工程边界

- 当前 Python 服务只用于本地演示，不是生产 WSGI/ASGI 服务。
- 没有认证、授权、限流、TLS、监控、审计、备份或持久化数据库。
- 没有在线执业兽医审核。
- 任何公网版本都需要单独的安全、隐私、合规和人工升级设计。

> 最后更新：2026-08-28
