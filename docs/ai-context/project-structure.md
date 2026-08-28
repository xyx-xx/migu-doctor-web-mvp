# 项目结构

```
migu/
├── index.html          # 首页
├── consult.html        # 三步症状信息采集
├── chat.html           # AI 追问与结构化结果
├── wiki.html           # 健康百科
├── emergency.html      # 确定性紧急分流
├── toxin.html          # 误食风险采集与提示
├── api_proxy.py        # 本地静态服务与模型代理
├── assets/
│   ├── styles.css      # 共用视觉系统
│   └── app.js          # API、状态和安全 DOM 工具
├── README.md           # 对外项目说明
├── requirements.txt    # Python 依赖
├── .env.example        # 无密钥的环境变量模板
├── CLAUDE.md           # AI 协作上下文入口
└── .claude/            # 协作命令、hook 与安全扫描
    ├── settings.json   # 权限和钩子配置
    ├── commands/       # 自定义命令
    └── skills/         # 自定义技能
```

> 最后更新：2026-08-28
