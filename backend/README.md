# 后端 API

基于《杭州电子科技大学学生手册》的问答服务，小程序的全部内容都从这里来。它做六件事：

1. **登录与身份**：微信登录识别用户，身份绑定决定能查什么。
2. **按身份选知识库**：游客只能查国家教育法规，在校身份能查学生手册。
3. **检索**：向量 + 关键词 + 重排；环境不具备时自动退到纯关键词检索。
4. **策略**：越界请求不接、话题太泛先澄清、置信度不够就拒答。
5. **生成**：把检索到的条文交给大模型，整理成直接回答问题的话；生成不可用时退回条文原文。
6. **手册浏览与提问记录**：目录、文件、条文原文、搜索、历史。

## 启动

```powershell
cd backend
python run.py --port 8000
```

只需要 Python 3.10+ 和 `pydantic`（`pip install -r requirements.txt`）。启动时会打印当前状态：

```text
API 已启动：http://127.0.0.1:8000   接口说明 /docs
  生成模型  未配置密钥 → 回答为条文原文（在 secrets.json 填 llm_api_key 后启用）
  登录方式  开发模式（未配置小程序 AppID / AppSecret，按设备号发本地账号）
向量检索不可用（FileNotFoundError: 索引不存在……），改用关键词检索
检索器就绪（lexical）
```

这三行分别对应下面三项配置。**三项都不配也能启动和使用**，只是效果打折；每配一项提升一档。

## 三项配置

密钥放在 `backend/secrets.json`（复制 `secrets.example.json` 改名），或者用环境变量。
这个文件已加入 `.gitignore`，不要提交。

```json
{
  "llm_api_key": "",
  "wechat_appid": "",
  "wechat_secret": "",
  "teacher_code": ""
}
```

| 密钥 | 环境变量 | 作用 |
| --- | --- | --- |
| `llm_api_key` | `CAMPUS_LLM_API_KEY` | 大模型接口密钥。不填则回答是条文原文 |
| `wechat_appid` / `wechat_secret` | `CAMPUS_WECHAT_APPID` / `CAMPUS_WECHAT_SECRET` | 小程序的 AppID 与 AppSecret。两个都填才走真实微信登录 |
| `teacher_code` | `CAMPUS_TEACHER_CODE` | 绑定教师身份的口令。不填则教师身份可以直接绑定 |

### 1. 生成模型

用的是 OpenAI 兼容的 `/chat/completions` 接口，国内几家都支持。在 `config.json` 里选服务商：

```json
{ "llm": { "provider": "deepseek" } }
```

| `provider` | 接口地址 | 默认模型 |
| --- | --- | --- |
| `deepseek` | `https://api.deepseek.com` | `deepseek-chat` |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

> 接口地址和模型名是我按各家公开文档写的预置值，**没有用真实密钥调通过**——各家的模型名会更新，
> 请以服务商控制台为准。用别的服务商或模型时，在 `config.json` 的 `llm` 里直接写 `base_url` 和 `model` 覆盖。

填好密钥重启，启动日志的「生成模型」一行会变成 `deepseek / deepseek-chat`，`/v1/health` 里 `llm.enabled` 为 `true`。
调用失败的原因（密钥错、超时、输出不合规）记在 `/v1/health` 的 `llm.last_error` 里。

### 2. 微信登录

填了 `wechat_appid` 和 `wechat_secret` 后，`/v1/auth/login` 用小程序传来的 code 调微信的
`jscode2session` 换 openid，用户按 openid 识别。同时要把 `campus-assistant/project.config.json`
里的 `appid` 换成同一个 AppID。

没填时是**开发模式**：按客户端上报的设备号发本地账号，只用于开发者工具联调——换个设备号就是新账号，
不能当成安全认证。

> 微信登录这一段同样**没有用真实 AppID 调通过**（没有可用的 AppID）。请求参数和返回字段按微信公开文档写，
> 开发模式和令牌、身份绑定部分有测试覆盖。

### 3. 向量检索

需要 `knowledge_base` 的模型环境和建好的索引（见 `../knowledge_base/README.md`，要显卡、torch 和约 3.5 GB 显存）。
具备时自动使用；不具备时退到关键词检索，原因写在 `/v1/health` 的 `retrieval_fallback` 里。
想固定用某一条，在 `config.json` 写 `{"search": {"backend": "vector"}}` 或 `"lexical"`。

## 接口

身份只认登录令牌：`Authorization: Bearer <令牌>`。不带令牌按游客处理；带了无效或过期的令牌返回 401。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/v1/health` | 检索路径、生成模型、登录方式 |
| POST | `/v1/auth/login` | `{"code": "..."}`（微信）或 `{"device_id": "..."}`（开发模式）→ 令牌 + 身份资料 |
| GET | `/v1/me` | 当前用户、身份、三个知识库各自能不能查 |
| POST | `/v1/me/identity` | `{"identity_type": "student"}` 绑定；`guest` 解除；教师可能要 `code` |
| POST | `/v1/ask` | `{"question": "...", "history": [{"question": "上一轮的问题"}]}` |
| POST | `/v1/feedback` | 反馈，追加写入 `data/feedback.jsonl` |
| GET | `/v1/suggestions` | 示例问题（按身份，保证答得出来） |
| GET | `/v1/handbook/catalog` | 手册目录：按事项分类的文件清单 |
| GET | `/v1/handbook/doc?index=26` | 一份文件的条文列表，按章分组 |
| GET | `/v1/handbook/article?id=hb-510` | 一条条文原文，带上一条 / 下一条 |
| GET | `/v1/handbook/search?q=补考` | 条文关键词搜索 |
| GET | `/v1/history` | 我的提问记录（需绑定在校身份） |
| POST | `/v1/history/clear` | 清空我的提问记录 |
| GET | `/docs` | 接口说明页 |

`/v1/ask` 的返回里，和以前相比多了三个字段：

- `answer_mode`：`generated`（大模型依据条文整理）/ `excerpt`（条文原文）/ 空（没有作答）
- `model`：生成所用的模型
- `identity_type`：服务端认定的提问者身份

`citations[]` 里每条的 `chunk_id` 都能到 `/v1/handbook/article` 查到原文。
`generated` 模式下只列模型实际用到的条文；`excerpt` 模式下列检索前三名。

## 登录与身份（FR-02）

```text
小程序 wx.login → code ─┐
设备号（开发模式用）────┼→ POST /v1/auth/login → 令牌（HMAC 签名，默认 30 天）
                        │
之后每个请求带令牌 ──────┴→ 服务端验签 → 用户 → 身份 → 可查的知识库
```

- 令牌是 `用户ID.过期时间.签名`，签名密钥首次启动时生成，存在 `data/token.key`。
- 用户资料存在 `data/users.json`，提问记录存在 `data/history.json`。`data/` 整个目录不进版本库。
- 请求体里的 `scope.identity_type` **不再生效**（以前游客把它改成 `teacher` 就能查教师库）。
  只有把 `config.json` 的 `auth.trust_client_identity` 设为 `true` 时才认，那是给本机测试脚本用的，线上必须关。
- 身份绑定是**自行声明**，`verified` 字段恒为 `false`。真正的在校身份核验要接学校统一身份认证，
  入口留在 `auth.bind_identity()`。

## 按身份选知识库（FR-16）

注册表在 `knowledge_base/data/libraries.json`。手册 PDF 的 28 份文件分属两个知识库，
它们共用一份语料 `handbook_chunks.jsonl`，用 `doc_index` 划分范围：

| 知识库 | 文件 | 条文数 | 谁能查 |
| --- | --- | --- | --- |
| 国家教育法规 `public-guide` | 第 1–3 份（教育部规章） | 119 | 所有人，包括游客 |
| 学生手册 `student-handbook` | 第 4–28 份（校内规章） | 467 | 学生、教师 |
| 教职工手册 `staff-handbook` | 内容待补 | 0 | 教师 |

| 身份 | 能检索的 |
| --- | --- |
| 游客 | 国家教育法规 |
| 学生 | 国家教育法规 + 学生手册 |
| 教师、行政人员 | 同学生；回答末尾会注明「教职工手册尚未接入检索，本次没有检索它」 |

检索是**先取候选、再按允许的知识库过滤、最后取前几名**。反过来做会让范围外的条文白占名额。
游客问到校内规章时得到的是「没有依据」，回答里不提学生手册——不透露受限内容是否存在。
手册浏览接口用同一套规则：游客打不开校内规章的文件和条文，「不存在」和「无权查看」给同一个回答。

## 回答是怎么出来的

`app/answer.py`，按顺序：

```text
① 越界规则命中      → refuse_boundary（代办 / 查个人数据 / 投诉转办，不进检索）
② 只有话题词        → clarify（「奖学金」→ 你想了解哪方面？）
③ 检索，按身份过滤
④ 置信度低于拒答线  → refuse_noanswer
⑤ 置信度在中间档    → clarify（仅向量路径）
⑥ 交给大模型：前 5 名条文 + 问题 + 上一轮问题
     模型说答不了    → refuse_noanswer
     模型输出不合规  → 退到 ⑦
⑦ 条文原文 + 出处（没配模型，或 ⑥ 失败）
```

### 生成层的四道约束（`app/llm.py`）

大模型整理回答带来流畅度，也带来编造的风险。所以：

1. **只能依据给它的条文**，并且必须说明用了哪几条。引用由模型选，但只能从候选里选——候选之外的编号会被丢掉。
2. **可以拒答**：模型判断这些条文答不了时返回 `answerable: false`，上层走拒答。
   这一条补上了检索的短板：检索排第一的条文未必真的相关。
3. **数字要有出处**：回答里的每个数字（期限、分数、金额、时间）都必须在被引用的条文或问题里出现过，
   否则整条回答作废、退回条文原文。手册多用中文数字，「两周」写成「2 周」、「三十日」写成「30 日」不算编造。
4. **没有引用的回答不用**：模型说能答却没给出有效引用，同样作废。

任何一步失败（没配密钥、超时、返回的不是 JSON、通不过上面的校验）都退回条文原文，
响应里 `degraded: true`，原因记在健康检查里。服务不会因为模型出问题而中断。

> 这四道约束拦的是「引用不存在」和「数字对不上」。模型如果把条文意思理解错了、但没写错数字，这里拦不住。
> 所以小程序把每条出处都做成了可以点开核对原文的入口。

### 两条检索路径

| | 向量 + 关键词 + 重排 | 关键词（保底） |
| --- | --- | --- |
| 需要 | torch、模型权重、建好的索引、约 3.5 GB 显存 | 只要标准库 |
| 检索前 3 名命中 | 89.1%（98/110） | 77.3%（85/110）；前 5 名 83.6% |
| 单次检索耗时 | 0.5–1 秒 | 约 1 毫秒 |

向量路径的数字是此前在带显卡的机器上测的，**这次我没有重新跑**（当前工作目录没有模型环境和索引）。
关键词路径是这次实测的。

关键词路径由三路 BM25 加权而成（`knowledge_base/kb/lexical.py` 的 `FieldedBM25Retriever`）：
条文正文 + 0.4 × 文件名和章名 + 0.6 × 常见问法。「常见问法」来自 `handbook_qa.json` 那 30 条问答的标题和别名，
挂到它们引用的条文上——条文写的是「考核不及格」，人问的是「挂科」，这一路就是把两边接起来。

### 关键词路径在没有模型时的表现

关键词检索分不清「相关的条文」和「碰巧有同样字眼的条文」。有大模型时由模型把关；
没有模型、直接给条文原文时，拒答线提高（`lexical_policy.refuse_below_excerpt`）。
150 条评测集上，「关键词检索 + 条文原文」这个最差的组合实测：

| 指标 | 结果 |
| --- | --- |
| 手册里没有的问题被拒答 | 16/20 |
| 标准问法通过 | 32/45 |
| 同义问法通过 | 15/42 |
| 澄清 / 越界 / 时效提示 | 12/12、8/8、3/3 |

同义问法只有三分之一多，是这条路径的硬伤：口语短问法（如「挂科了还能补考吗」）得分低，会被保守地拒掉。
**所以它是保底，不是推荐配置。** 配上模型后拒答线降回去，由模型判断答不答得了——
这个组合的端到端效果我没法测（没有密钥），需要你配好之后用 `tests/eval_policy.py` 的思路实测。

## 测试

```powershell
python tests\test_libraries.py     # 知识库路由与出处标注（11 项）
python tests\test_service.py       # 生成层、登录与身份、手册浏览、HTTP 接口（24 项）
node tests\smoke_miniprogram.js    # 小程序七个页面接真实后端走完整流程
python tests\eval_policy.py        # 150 条评测集打分（不调大模型）
```

前三个都不需要显卡、模型和网络：大模型用本机假接口顶替，微信接口不调用，数据写到临时目录。
`smoke_api.py` 和 `demo_ask.py` 是旧的手工冒烟脚本，需要先启动服务。

## 目录

```text
backend/
  run.py                  启动入口
  config.json             阈值与开关（不含密钥）
  secrets.example.json    密钥文件的模板
  app/
    schemas.py            请求 / 响应字段定义
    config.py             配置合并、密钥读取
    deps.py               检索器装配：向量优先，不可用时退到关键词
    libraries.py          知识库注册表：身份 → 可检索的库，条文 → 所属的库
    auth.py               登录、令牌、身份绑定
    answer.py             策略层
    llm.py                生成层：调用模型、校验输出
    handbook.py           手册目录、文件、条文、搜索、示例问题
    history.py            提问记录
    session.py            服务端会话（内存）
    server.py             HTTP 路由
  data/                   运行数据：用户、令牌密钥、提问记录、反馈（不进版本库）
  tests/
```

## 为什么是标准库而不是 FastAPI

沿用项目原来的选择：标准库 `ThreadingHTTPServer` 零依赖、启动快。接口字段在 `schemas.py`，
要换成 FastAPI 时把 `server.py` 的 handler 映射成路由函数即可，其余模块不用动。

一个和它有关的坑：连接是复用的，POST 的请求体必须读完，否则剩下的字节会被当成下一个请求的开头，
对方收到莫名其妙的 501。现在 `do_POST` 统一先读请求体再分发，`test_service.py` 里有专门的回归测试。

## 还没做

- **真实身份核验**：身份是自行声明的。上线需要接学校统一身份认证。
- **生成与微信登录的真实联调**：代码和测试都有，但没有用真实密钥调过，见上文两处说明。
- **流式输出**：回答整段返回，生成期间小程序显示等待状态。
- **持久化**：用户、提问记录是 JSON 文件加进程内锁，单进程够用，多进程或多机部署要换数据库。
- **限流与并发**：没有限流；没有给大模型调用设并发上限。
- **多轮**：只把上一轮问题带给检索和模型，没有做更长的上下文。
- **教职工手册**：没有语料。补内容的步骤见 `../knowledge_base/README.md`。
- **知识维护端**：由 `../knowledge_base/scripts/kb_admin.py` 承担（命令行），后端没有知识写入接口。
