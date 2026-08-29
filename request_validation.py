"""模型代理的请求与响应校验规则。

这个模块不依赖 HTTP 或模型 SDK，便于独立测试安全边界。
"""

import json
import re


MAX_MESSAGES = 24
MAX_MESSAGE_CHARS = 6_000
MAX_TOTAL_CHARS = 28_000
MAX_OUTPUT_TEXT_CHARS = 4_000

ALLOWED_TASKS = frozenset(
    {"triage_questions", "triage_result", "triage_followup", "wiki"}
)
ALLOWED_ROLES = frozenset({"user", "assistant"})
RISK_LEVELS = frozenset(
    {"OBSERVE_WITH_GUARDRAILS", "CONTACT_VET_NOW", "EMERGENCY_NOW"}
)
RISK_LABELS = {
    "OBSERVE_WITH_GUARDRAILS": "可在安全边界内观察",
    "CONTACT_VET_NOW": "现在联系执业兽医",
    "EMERGENCY_NOW": "立即前往宠物医院",
}


def validate_task(value):
    """只接受服务端已经定义并拥有提示词的任务。"""
    if not isinstance(value, str) or value not in ALLOWED_TASKS:
        allowed = "、".join(sorted(ALLOWED_TASKS))
        raise ValueError(f"task 必须是以下值之一：{allowed}")
    return value


def validate_messages(value):
    """限制角色、字段、消息数量与长度，拒绝浏览器注入系统提示词。"""
    if not isinstance(value, list) or not value:
        raise ValueError("messages 必须是非空数组")
    if len(value) > MAX_MESSAGES:
        raise ValueError(f"单次最多发送 {MAX_MESSAGES} 条消息")

    cleaned = []
    total_chars = 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("每条消息必须是对象")
        if set(item) != {"role", "content"}:
            raise ValueError("每条消息只能包含 role 和 content")

        role = item.get("role")
        content = item.get("content")
        if role not in ALLOWED_ROLES:
            raise ValueError("消息角色只能是 user 或 assistant")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("消息内容不能为空")

        content = content.strip()
        if len(content) > MAX_MESSAGE_CHARS:
            raise ValueError(f"单条消息不能超过 {MAX_MESSAGE_CHARS} 个字符")
        total_chars += len(content)
        if total_chars > MAX_TOTAL_CHARS:
            raise ValueError("本次对话内容过长，请精简后重试")
        cleaned.append({"role": role, "content": content})

    if cleaned[-1]["role"] != "user":
        raise ValueError("最后一条消息必须来自 user")
    return cleaned


def validate_assist_request(payload):
    """校验 /api/assist 的完整请求，不允许浏览器传入 model 等控制字段。"""
    if not isinstance(payload, dict):
        raise ValueError("请求正文必须是 JSON 对象")
    if set(payload) != {"task", "messages"}:
        raise ValueError("请求只能包含 task 和 messages")
    return validate_task(payload.get("task")), validate_messages(payload.get("messages"))


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("模型 JSON 包含重复字段")
        result[key] = value
    return result


def parse_model_json(content):
    """严格解析模型 JSON：拒绝代码围栏、非对象、重复键和 NaN/Infinity。"""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型返回了空内容")

    def reject_constant(_value):
        raise ValueError("模型 JSON 包含非法数值")

    try:
        parsed = json.loads(
            content.strip(),
            object_pairs_hook=_json_object,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("模型没有返回有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("模型 JSON 必须是对象")
    return parsed


def _clean_output_string(value, field, max_chars=1_000):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    cleaned = value.strip()
    if len(cleaned) > max_chars:
        raise ValueError(f"{field} 内容过长")
    return cleaned


def _clean_string_list(value, field, minimum=1, maximum=8, item_chars=500):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} 必须包含 {minimum} 到 {maximum} 项")
    cleaned = []
    for item in value:
        text = _clean_output_string(item, field, item_chars)
        if text in cleaned:
            raise ValueError(f"{field} 不能包含重复项")
        cleaned.append(text)
    return cleaned


def validate_questions_result(value):
    """校验 triage_questions 的模型 JSON。"""
    if not isinstance(value, dict) or set(value) != {"questions"}:
        raise ValueError("追问结果只能包含 questions")
    return {
        "questions": _clean_string_list(
            value.get("questions"), "questions", minimum=2, maximum=3, item_chars=240
        )
    }


def validate_triage_result(value):
    """校验并规范化结构化分流结果。"""
    required = {"risk", "riskLabel", "rationale", "actions", "emergencySigns"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("分流结果字段不完整或包含未知字段")

    risk = value.get("risk")
    if risk not in RISK_LEVELS:
        raise ValueError("risk 不是允许的风险枚举")

    # riskLabel 必须由模型提供，但返回给浏览器的文案由服务端按枚举统一。
    _clean_output_string(value.get("riskLabel"), "riskLabel", 80)
    return {
        "risk": risk,
        "riskLabel": RISK_LABELS[risk],
        "rationale": _clean_output_string(value.get("rationale"), "rationale", 1_200),
        "actions": _clean_string_list(value.get("actions"), "actions"),
        "emergencySigns": _clean_string_list(
            value.get("emergencySigns"), "emergencySigns"
        ),
    }


def _normalize_plain_text(content):
    """移除模型偶尔忽略提示词时带回的基础 Markdown，前端始终按纯文本显示。"""
    if not isinstance(content, str):
        return content
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", content)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\[([^\]\n]+)\]\([^\n)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "• ", text)
    return text.strip()


def validate_text_result(content):
    return {
        "text": _clean_output_string(
            _normalize_plain_text(content), "text", MAX_OUTPUT_TEXT_CHARS
        )
    }


_UNSAFE_PATTERNS = (
    re.compile(r"(?:自行|自己|在家|人工|设法)?(?:催吐|诱吐|诱导(?:宠物)?呕吐|让(?:它|宠物)[^。；\n]{0,8}吐出来)"),
    re.compile(r"(?:抠|刺激|触碰)[^。；\n]{0,8}(?:喉咙|咽喉|舌根)"),
    re.compile(r"(?:3\s*%\s*)?(?:双氧水|过氧化氢)[^。；\n]{0,24}(?:催吐|诱吐|呕吐)"),
    re.compile(r"(?:催吐|诱吐)[^。；\n]{0,24}(?:双氧水|过氧化氢)"),
    re.compile(r"(?:盐水|食盐|浓盐水|盐)[^。；\n]{0,18}(?:催吐|诱吐|呕吐)"),
    re.compile(r"(?:催吐|诱吐)[^。；\n]{0,18}(?:盐水|食盐|浓盐水|盐)"),
    re.compile(r"(?:强行|强制|硬要|灌)(?:给(?:它|宠物))?(?:喂食|喂水|灌食|灌水|进食|喝水)"),
    re.compile(r"(?:灌食|灌水|灌药)"),
    re.compile(r"(?:针管|注射器)[^。；\n]{0,12}(?:喂食|喂水|灌食|灌水|灌药)"),
    re.compile(
        r"(?:给(?:它|宠物|猫|狗)|喂(?:它|宠物|猫|狗)?|灌(?:它|宠物|猫|狗)?|使用)"
        r"[^。；\n]{0,18}(?:双氧水|过氧化氢|浓盐水|盐水)"
    ),
    re.compile(
        r"(?:剂量|每公斤|口服|注射|服用|给药|用药)[^。；\n]{0,36}"
        r"\d+(?:\.\d+)?\s*(?:mg|g|ml|毫克|克|毫升|片|粒|滴|勺|茶匙|单位)(?:\s*/\s*kg)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:给(?:它|宠物|猫|狗)|喂(?:它|宠物|猫|狗)?|使用)[^。；\n]{0,28}"
        r"(?:\d+(?:\.\d+)?|半|一|两|二|三|四|五)\s*"
        r"(?:mg|g|ml|毫克|克|毫升|片|粒|滴|勺|茶匙|单位)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\d+(?:\.\d+)?\s*(?:mg|毫克|g|克|ml|毫升|单位)\s*/\s*kg",
        re.IGNORECASE,
    ),
)

# 这些规则单独处理，避免把“正在服药吗”“请携带药品包装”等病例资料误判为
# 给药建议。模型一旦肯定式要求家庭用药、服药或改剂量，仍然一律 fail closed。
_MEDICATION_ACTION_PATTERN = re.compile(
    r"(?:口服|服用|服药|吃药|喂药|给药|投药|灌药|用药|使用药物)"
)
_DOSE_ACTION_PATTERN = re.compile(
    r"(?:调整|改变|增加|减少|加大|降低|加倍|减半|增量|加量|减量|停药|换药|改药|加药|减药)"
)
_DOSE_NOUN_PATTERN = re.compile(r"(?:药量|用量|剂量|给药量|用药剂量)")
_INHERENT_DOSE_ACTIONS = frozenset(
    {"加倍", "减半", "增量", "加量", "减量", "停药", "换药", "改药", "加药", "减药"}
)

# 药名只在同一短句中同时出现“使用/给予/推荐”动作时才拦截。单纯说明
# “布洛芬对猫有毒”或要求携带药品包装，不属于给药建议。
_DRUG_NAME_PATTERN = re.compile(
    r"(?:"
    r"阿莫西林|氨苄西林|青霉素|头孢[\u4e00-\u9fffA-Za-z0-9-]{0,8}|"
    r"布洛芬|对乙酰氨基酚|扑热息痛|阿司匹林|蒙脱石散|奥美拉唑|"
    r"多潘立酮|庆大霉素|诺氟沙星|左氧氟沙星|环丙沙星|甲硝唑|"
    r"地塞米松|泼尼松|强的松|氯雷他定|西替利嗪|苯海拉明|"
    r"马罗匹坦|甲氧氯普胺|呋塞米|胰岛素|卡洛芬|美洛昔康|"
    r"多西环素|伊维菌素|"
    r"[\u4e00-\u9fff]{1,8}(?:西林|霉素|沙星|硝唑|昔康|拉唑|司匹林)|"
    r"amoxicillin|ampicillin|ibuprofen|acetaminophen|paracetamol|aspirin|"
    r"meloxicam|metronidazole|omeprazole"
    r")",
    re.IGNORECASE,
)
_DRUG_ADVICE_ACTION_PATTERN = re.compile(
    r"(?:建议|推荐|选用|改用|换用|使用|服用|口服|喂服|给予|给(?:它|宠物|猫咪?|狗狗?)(?:吃|喂|用)|"
    r"让(?:它|宠物|猫咪?|狗狗?)(?:吃|服用|口服)|吃|注射|涂抹)"
)
_DRUG_SUGGESTION_ACTIONS = frozenset({"建议", "推荐"})

_NEGATIONS = (
    "不要",
    "不得",
    "切勿",
    "禁止",
    "避免",
    "不可",
    "不能",
    "勿",
    "不建议",
    "不太建议",
    "不推荐",
    "不应该",
    "不应",
    "不可以",
    "不宜",
    "无需",
    "无须",
)
_POSITIVE_AFTER_NEGATION = re.compile(
    r"(?:但|但是|不过|然而|却|反而|仍然|仍|建议|推荐|可以|应该|应当|需要|立即|先)"
)
_NON_ADVICE_MEDICATION_CONTEXT = re.compile(
    r"(?:是否(?:正在|需要|应该|可以)?|有无|有没有|何时|哪种|什么|"
    r"已经|曾经|正在|目前正在|此前|之前|刚刚|误服|不慎服用)"
    r"[^。！？；，,\n]{0,10}$"
)


def _match_is_negated(text, start):
    # 某些建议动作本身是“建议/推荐”，否定词会跨过 match 起点：
    # “不建议使用阿莫西林”中的 match 可能从“建议”开始。
    for word in _NEGATIONS:
        window_start = max(0, start - len(word))
        position = text.rfind(word, window_start, start + len(word))
        if position >= 0 and position <= start < position + len(word):
            return True

    prefix = text[:start]
    # 只考察当前短句，避免上一句里的否定词掩盖后面的危险建议。
    prefix = re.split(r"[。！？；，,\n]", prefix)[-1]
    latest = None
    for word in _NEGATIONS:
        position = prefix.rfind(word)
        if position >= 0 and (latest is None or position > latest[0]):
            latest = (position, word)
    if latest is None:
        return False

    # “不要……，建议……”由标点切开；没有标点时也不能让前面的否定词
    # 掩盖后面重新出现的肯定式建议。
    position, word = latest
    after_negation = prefix[position + len(word) :]
    return _POSITIVE_AFTER_NEGATION.search(after_negation) is None


def _match_is_non_advice_medication_context(text, start):
    prefix = re.split(r"[。！？；，,\n]", text[:start])[-1]
    return _NON_ADVICE_MEDICATION_CONTEXT.search(prefix) is not None


def _clause_bounds(text, position):
    """返回 position 所在中文短句的 [start, end) 边界。"""
    previous = [text.rfind(mark, 0, position) for mark in "。！？；，,\n"]
    start = max(previous) + 1
    following = [text.find(mark, position) for mark in "。！？；，,\n"]
    following = [item for item in following if item >= 0]
    end = min(following) if following else len(text)
    return start, end


def contains_unsafe_advice(value):
    """检测模型是否给出被禁止的家庭处置、用药或剂量建议。"""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    for pattern in _UNSAFE_PATTERNS:
        for match in pattern.finditer(text):
            if not _match_is_negated(text, match.start()):
                return True

    # 肯定式口服/服药/家庭用药不需要带具体剂量，也属于越界处方建议。
    for match in _MEDICATION_ACTION_PATTERN.finditer(text):
        if _match_is_negated(text, match.start()):
            continue
        if _match_is_non_advice_medication_context(text, match.start()):
            continue
        return True

    # “把药量减半”和“调整用药剂量”都应被拦截；否定式安全说明保留。
    for match in _DOSE_ACTION_PATTERN.finditer(text):
        action = match.group(0)
        clause_start, clause_end = _clause_bounds(text, match.start())
        clause = text[clause_start:clause_end]
        if action not in _INHERENT_DOSE_ACTIONS and not _DOSE_NOUN_PATTERN.search(
            clause
        ):
            continue
        if not _match_is_negated(text, match.start()):
            return True

    # 给出药名本身可以是风险说明；只有同句出现肯定式使用/给予动作才丢弃。
    for drug_match in _DRUG_NAME_PATTERN.finditer(text):
        clause_start, clause_end = _clause_bounds(text, drug_match.start())
        clause = text[clause_start:clause_end]
        for action_match in _DRUG_ADVICE_ACTION_PATTERN.finditer(clause):
            action_start = clause_start + action_match.start()
            if _match_is_negated(text, action_start):
                continue
            if action_match.group(0) in _DRUG_SUGGESTION_ACTIONS:
                following = clause[action_match.end() :]
                if any(word in following for word in _NEGATIONS):
                    continue
            if _match_is_non_advice_medication_context(text, action_start):
                continue
            return True
    return False
