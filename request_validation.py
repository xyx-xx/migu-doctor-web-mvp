"""模型代理请求的纯 Python 校验规则。"""

MAX_MESSAGES = 24
MAX_MESSAGE_CHARS = 6_000
MAX_TOTAL_CHARS = 28_000
ALLOWED_ROLES = {"system", "user", "assistant"}


def validate_messages(value):
    """限制角色、消息数量与长度，避免把任意大请求转发给模型。"""
    if not isinstance(value, list) or not value:
        raise ValueError("messages 必须是非空数组")
    if len(value) > MAX_MESSAGES:
        raise ValueError(f"单次最多发送 {MAX_MESSAGES} 条消息")

    cleaned = []
    total_chars = 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("每条消息必须是对象")
        role = item.get("role")
        content = item.get("content")
        if role not in ALLOWED_ROLES:
            raise ValueError("消息角色不合法")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("消息内容不能为空")
        content = content.strip()
        if len(content) > MAX_MESSAGE_CHARS:
            raise ValueError(f"单条消息不能超过 {MAX_MESSAGE_CHARS} 个字符")
        total_chars += len(content)
        if total_chars > MAX_TOTAL_CHARS:
            raise ValueError("本次对话内容过长，请精简后重试")
        cleaned.append({"role": role, "content": content})
    return cleaned
