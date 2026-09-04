# 棋牌游戏舆情推送机器人

面向中国棋牌游戏行业的钉钉舆情监控服务。当前版本使用自定义机器人 Webhook 单向推送，后续可平滑增加 Stream 机器人问答入口。

## 当前能力

- 每 30 分钟通过国内聚合检索与主流媒体 RSS 发现监管执法、资本组织、产品经营和平台渠道新闻。
- 结合行业相关性、事件影响、信源级别和时效性进行 100 分制评分。
- 过滤泛游戏、泛金融内容，按相似标题抑制重复推送。
- 只即时推送达到阈值且信源等级不低于行业媒体的新闻。
- 原文页面必须以中文为主；英文、日文、韩文及无法核验语言的页面不推送。
- 当单轮严格棋牌新闻少于 2 条时，可补充 1 条国产头部网游重大新闻，且单轮最多 1 条。
- 按事件类型使用“交易要点 / 标的画像 / 行业影响”等专业结构，隐藏内部评分和分类过程。
- 首次启动只建立历史基线，默认不会把旧新闻集中推入群聊。

## 安全准备

聊天记录中出现过的 Webhook 应视为已经泄露，请先在钉钉群机器人设置中重置安全凭证。不要将真实 Webhook 写入配置或提交到 Git。

创建 `.env`：

```powershell
Copy-Item .env.example .env
```

将重置后的地址填写到 `.env`，不要填写到 `.env.example`：

```dotenv
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=NEW_TOKEN
```

机器人自定义关键词必须保留为“信源”；程序会在正文底部的信源栏带上该关键词。钉钉的自定义关键词校验要求可参考[官方安全设置文档](https://open.dingtalk.com/document/robots/customize-robot-security-settings)。

## 本地运行

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\qipai-news-bot --config config/config.yaml --dry-run
.venv\Scripts\qipai-news-bot --config config/config.yaml --test-webhook
.venv\Scripts\qipai-news-bot --config config/config.yaml
```

`--dry-run` 只在终端输出达到阈值的推送，不访问钉钉 Webhook。`--test-webhook` 只发送一条连通性测试，不启动新闻轮询。确认内容后，再运行正式服务。
本地命令会自动加载项目根目录的 `.env`；已经在系统环境变量中设置的值优先级更高。

## Docker 运行

```powershell
docker compose up -d --build
docker compose logs -f newsbot
```

## Windows 后台自启

安装当前用户登录后自动运行的计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows_task.ps1
```

任务名为 `QipaiNewsBot`，通过 `pythonw.exe` 无窗口运行。用户登录时启动，并由每 5 分钟一次的看门狗触发补偿；正常运行时忽略重复实例，异常退出后最迟约 5 分钟恢复。日志写入 `data/newsbot.log`。

修改 `.env` 或配置后，重启后台任务使其生效：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restart_windows_task.ps1
```

卸载：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall_windows_task.ps1
```

## 调整规则

编辑 `config/config.yaml`：

- `searches`：配置国内检索关键词；当前使用 360 资讯、头条搜索和搜狗微信搜索。
- `feeds`：当前接入新华社财经、中国新闻网财经、新浪财经及垂直游戏媒体 RSS。
- `companies`：补充重点企业、产品和竞品名称。
- `company_profiles`：维护重点公司的核心产品、业务模式和行业位置。
- `safety`：维护政治敏感词、敏感人名、保护主体、未核实消息和指控性关键词；命中后仅落库记录，不向群聊推送。
- `fallback`：控制国产网游与国内 AI/科技重大新闻补位池；两类新闻各有单轮 1 条名额，仅在棋牌推送不足时启用，默认最低 70 分。国产游戏池重点跟踪爆款小游戏、买量投放、IAA/IAP/混合变现、流水、留存与 ROI 变化。
- `daily_backup`：前一自然日零推送时，在次日 09:30 后从近 72 小时安全、可信、中文的备选内容中按分数固定发送 3 条；不足时每轮继续补选，直至当日补满。
- `instant_push_score`：即时推送阈值，默认 70 分。
- `maximum_item_age_hours`：拒绝旧闻的时间窗口，默认 72 小时。
- `maximum_core_event_age_hours`：核心信息披露或发生时间的时效窗口，默认 72 小时；即使文章刚发布，复述旧事件也不推送。
- `maximum_alerts_per_cycle`：单轮发送上限，避免突发刷屏。
- `send_on_first_run`：是否在首次启动推送历史窗口内新闻，默认关闭。

## 推送口径

消息按以下结构输出：

1. **事件要点**：按事件类型显示“交易要点”“案情要点”“政策要点”等标题，只提取与棋牌业务直接相关的事实。
2. **业务画像**：补充涉事公司的核心产品、区域玩法、业务模式和历史行业位置。
3. **行业影响**：从产品、团队、渠道、区域运营、用户和风控分析。
4. **信源**：在消息底部最多展示三个来源和一条原文链接，不展示内部评分、等级和命中词。

免费发现入口包括新华社财经、中国新闻网财经、新浪财经、360资讯、头条搜索、搜狗微信搜索、游戏陀螺、游戏茶馆和钛媒体。聚合搜索仅用于发现线索，不被视为事实来源；百度新闻因自动访问频繁触发安全验证，未纳入无人值守检索。网页入口可能调整结构，单一来源失败不会阻塞其他来源。
