# 校园智能问答系统

把《杭州电子科技大学学生手册》（2017 年 9 月版，206 页、28 份文件）做成一个微信小程序里的问答助手。

学生用平常的话提问，后端从手册里检索出相关条文，交给大模型整理成直接回答问题的话，
并且**每条回答都标明出自哪份文件、哪一条、第几页，点开就能核对原文**。
查不到就明说查不到；要求代办或查个人数据的，说明不办并指明该去哪里。

---

## 效果

```
问：宿舍几点熄灯？
答：（大模型依据条文整理的回答）
依据以下条文整理：第二十二条 《杭州电子科技大学学生住宿管理规定》 第 174 页   ← 可点开看原文

问：图书馆几点开门？
答：当前检索的知识库（国家教育法规、学生手册）里没有足够可靠的依据回答这个问题，我不做推测。

问：帮我报修一下宿舍漏水。
答：这里只提供制度和流程说明，不代为受理、不派发工单、不承诺办理结果。   ← 越界请求直接拦截，不进检索
```

没有配置大模型密钥时，第一问的回答是条文原文（其余不变）。

## 能力与边界

| 能做 | 不能做 |
| --- | --- |
| 按语义检索手册条文（同义改写也能命中，如「两门考试撞了」→ 缓考条） | 不查任何个人业务数据（成绩、课表、余额、处分记录） |
| 每条回答附出处（文件 + 条号 + 页码） | 不代为办理、不派单、不催办、不接受投诉转办 |
| 知识库里没有的，明确拒答并给官方渠道 | 不编造政策、日期、电话、金额 |
| 提问模糊时先反问，而不是猜一个答案 | 不替代学校各业务系统（选课、缴费、报销） |
| 手册条款可能过期时，追加「以现行文件为准」 | 不承诺知识库外的校园政策 |

## 架构

```text
┌──────────────────────────┐
│ 微信小程序                │  campus-assistant/
│ 首页 / 问答 / 我的        │  只负责界面与会话展示
└───────────┬──────────────┘
            │ HTTPS  POST /v1/ask
┌───────────▼──────────────┐
│ 后端（Python 标准库）     │  backend/
│ 越界拦截 → 澄清 → 检索    │  /v1/ask  /v1/feedback  /v1/health
│ → 置信度分档 → 作答/拒答  │
└───────────┬──────────────┘
            │ 进程内调用
┌───────────▼──────────────┐
│ 检索层                   │  knowledge_base/kb/
│ 向量(bge) + BM25 → 重排  │  索引 579 单元 × 1024 维
└───────────┬──────────────┘
            │
┌───────────▼──────────────┐
│ 语料                     │  knowledge_base/data/
│ 586 条条文块（带页码）    │  handbook_chunks.jsonl
└──────────────────────────┘
```

## 目录结构

```text
AI_chat/
├─ knowledge_base/              知识库与检索（Python）
│  ├─ data/                     语料、问答条目、评测集
│  │  ├─ handbook_chunks.jsonl  586 条条文块（文件/条号/页码/正文）
│  │  ├─ handbook_qa.json       30 条人工整理的问答条目
│  │  ├─ eval_questions.json    150 条评测问题（含标准答案与期望行为）
│  │  └─ handbook_fulltext.txt  206 页清洗后全文（供人工校对）
│  ├─ kb/                       检索层：配置/语料/嵌入/索引/融合/重排/指标
│  ├─ scripts/                  解析 PDF、建索引、评测、打分、自检
│  └─ requirements.txt
├─ backend/                     问答 API（Python 标准库 + pydantic）
│  ├─ app/auth.py               登录、令牌、身份绑定
│  ├─ app/answer.py             策略层：越界/澄清/拒答/作答
│  ├─ app/llm.py                生成层：调用大模型并校验输出
│  ├─ app/handbook.py           手册目录、条文原文、搜索
│  ├─ app/server.py             HTTP 路由
│  └─ tests/                    路由、服务、小程序联调、策略评测
└─ campus-assistant/            微信小程序（不带知识内容，全部来自后端）
   ├─ miniprogram/pages/        首页 / 问答 / 手册 / 我的 / 文件 / 条文原文 / 提问记录
   ├─ miniprogram/utils/api.js  唯一的联网入口：登录、令牌、全部接口
   └─ scripts/check.js          本地检查（结构、语法、联网规则、本机状态逻辑）
```

## 最快跑起来（不需要显卡）

```powershell
cd backend
pip install -r requirements.txt
python run.py --port 8000
```

然后用微信开发者工具导入 `campus-assistant` 目录并编译。这样跑起来的是最低配置：
关键词检索、回答为条文原文、开发模式登录。**想要像样的效果，按 [backend/README.md](backend/README.md) 配三样东西**：

| 配置 | 不配时 | 配了之后 |
| --- | --- | --- |
| 大模型密钥（DeepSeek / 通义千问 / 智谱） | 回答是条文原文 | 回答是依据条文整理的自然语言 |
| 小程序 AppID 与 AppSecret | 按设备发本地账号 | 真实微信登录 |
| 向量模型与索引（下面的复现步骤） | 关键词检索，口语问法容易查不到 | 语义检索，前 3 名命中 89.1% |


---

## 复现步骤

### 前置条件

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 | 脚本是 PowerShell；其他系统把命令换成对应写法即可 |
| Python | 3.11（3.10+ 可用） | 需要能 `pip install` |
| PyTorch | 2.6.0 + CUDA 12.4 | 有 NVIDIA 显卡时装 CUDA 版；纯 CPU 也能跑，只是慢 10–20 倍 |
| 显存 | 8 GB 可用 | 两个模型合计约 3.4 GB |
| 磁盘 | 8 GB 空闲 | 模型 3.4 GB + 虚拟环境 |
| 微信开发者工具 | 最新稳定版 | 只有跑前端时需要 |

> 本项目验证环境：Python 3.11.7、torch 2.6.0+cu124、transformers 4.56.2、tokenizers 0.22.2、
> huggingface-hub 0.34.0、pydantic 1.10.12、numpy 1.26.4、RTX 4060 Laptop 8 GB。

### 第 1 步：取代码

```powershell
git clone https://github.com/w66167/AI_chat.git
cd AI_chat
```

仓库里**不含模型和索引**（合计 3.4 GB，见「为什么不提交模型」），下一步会自动下载。

### 第 2 步：准备 Python 环境

一条命令（推荐）：

```powershell
cd knowledge_base
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
```

它会建 `.venv`（复用系统已装的 torch/numpy）、装固定版本依赖、跑自检。

<details>
<summary>手动执行（脚本被安全策略拦截时用这个）</summary>

```powershell
cd knowledge_base
python -m venv --system-site-packages .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# torch 若未装：
# .\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu124
```
</details>

### 第 3 步：下载模型并建索引

```powershell
cd knowledge_base
.\.venv\Scripts\python.exe scripts\build_index.py
```

首次运行会从 ModelScope 下载 bge-large-zh-v1.5（1.24 GB）与 bge-reranker-v2-m3（2.19 GB），
然后编码 586 个知识块、生成带指纹的索引（约 2 MB）。**之后不再重复下载。**

预期输出：

```
完成：586 个引用单元 → 579 个检索单元，维度 1024
耗时 32.0 秒，索引 .../bge-large-zh-v1.5.npz (2.1 MB)，指纹 <16 位>
```

### 第 4 步：自检

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
```

逐项检查依赖、CUDA、配置、语料、模型缓存、索引指纹，失败会给具体修法。

### 第 5 步：跑评测，对照预期分数

```powershell
# 检索路径对比（bm25 / vector / hybrid / +rerank）
.\.venv\Scripts\python.exe scripts\embed_bench.py

# 策略层端到端打分（150 题）
cd ..\backend
..\knowledge_base\.venv\Scripts\python.exe tests\eval_policy.py
..\knowledge_base\.venv\Scripts\python.exe ..\knowledge_base\scripts\score_eval.py `
    --predictions ..\knowledge_base\data\predictions_policy.json
```

分数应与下表一致（±1 条题的浮动属正常，GPU 与库版本会影响排序）。

### 第 6 步：启动后端

```powershell
cd backend          # 若上一步已在 backend 目录则跳过
..\knowledge_base\.venv\Scripts\python.exe run.py --port 8000
```

启动日志里看到「检索器就绪（vector）」说明向量检索已生效（显示 `lexical` 则是退到了关键词检索，原因在上一行）。
加载模型约需 25–30 秒，期间 `/v1/health` 返回 `status=warming`。

```powershell
# 另开一个窗口验证
curl.exe -s http://127.0.0.1:8000/v1/health
```

接口说明在 <http://127.0.0.1:8000/docs>。问答接口需要先登录拿令牌，不带令牌按游客处理（只能查国家教育法规）。
大模型密钥和微信登录的配置见 [backend/README.md](backend/README.md)。

### 第 7 步：跑小程序

1. 微信开发者工具 → 导入项目
2. 目录选 **`campus-assistant`**（不是里面的 `miniprogram`）
3. AppID 选「测试号」或游客模式；后端服务选「不使用云服务」
4. 点「编译」

首页顶上应显示「游客，可查国家教育法规」。如果显示「连不上问答服务」，说明后端没启动或地址不对
（`campus-assistant/miniprogram/utils/api.js` 的 `BASE_URL`）。小程序不带知识内容，后端不可用时不会给出回答。

在「我的」页绑定身份（游客 / 学生 / 教师、行政人员），身份决定能查什么：
游客＝国家教育法规（手册前 3 份文件），学生＝＋学生手册 25 份校内规章，教师另有教职工手册（内容待补）。
**身份由后端按登录令牌认定**，客户端改请求参数冒充不了；但目前身份是自行声明的，没有接学校统一身份认证。

**知识维护人员与知识审核员不在小程序里**，职责由管理端工具 `knowledge_base/scripts/kb_admin.py` 承担：
起草 → 提交 → 驳回/发布 + 审计，含「禁止作者自审」与版本递增。

改完代码想先做静态检查，不打开工具也行：

```powershell
cd campus-assistant
node scripts/check.js                        # 小程序本地检查（不需要后端）
python scripts/check-wxml.py                 # WXML 标签闭合

cd ..\backend
python tests\test_libraries.py               # 按身份选库与出处标注（11 项）
python tests\test_service.py                 # 生成层、登录与身份、手册浏览、HTTP 接口（24 项）
node tests\smoke_miniprogram.js              # 小程序七个页面接真实后端走完整流程

cd ..\knowledge_base
python scripts\export_libraries.py --check   # 注册表前后端是否同步
python scripts\kb_admin.py selftest          # 管理端知识维护/审核规则
```

这些都不需要显卡、模型和网络。

演示顺序与讲解要点见 [campus-assistant/DEMO.md](campus-assistant/DEMO.md)。

---

## 预期结果

### 检索质量（150 条评测集，110 道有标准答案）

| 检索路径 | Top-3 命中 | 110 题耗时 |
| --- | --- | --- |
| BM25（二元组） | 72.7% | 0.2 s |
| 向量（bge-large-zh-v1.5） | 78.2% | 3.3 s |
| 混合（向量 + BM25，RRF） | 80.0% | 2.6 s |
| 向量 + 重排 | 90.0% | 115 s |
| **混合 + 重排（默认）** | **90.9%** | 119 s |

### 策略层（端到端，150 题）

| 指标 | 实测 | 验收目标 |
| --- | --- | --- |
| 无答案正确拒答率 | **100%**（20/20） | ≥ 95% |
| 澄清题正确率 | **100%**（12/12） | ≥ 90% |
| 越界合规率 | **100%**（8/8） | 无承诺性表述 |
| 时效提示 | **100%**（3/3） | — |
| 标准问 | 93.3%（42/45） | — |
| 同义问法 | 71.4%（30/42） | 召回不足，已知短板 |
| 纯检索 Top-3（真实链路） | 89.1%（98/110） | ≥ 90% |
| 端到端通过率 | 81.8%（90/110） | ≥ 90% |

> 上表是「向量 + 重排、回答为条文原文」的成绩，在带显卡的机器上测得，接入大模型和关键词保底路径之后没有重测。
> 关键词保底路径的实测成绩见 [backend/README.md](backend/README.md)。
>
> 90.9% 与 89.1% 是两个口径：前者是离线检索对比（只比检索），后者走真实后端（多轮题只在问题短于 24 字时才拼上一轮，且拒答算失败）。**验收以 89.1% 为准。**

### 延迟（单机 RTX 4060 Laptop）

| 环节 | 平均 | P95 |
| --- | --- | --- |
| 查询向量化 | 16 ms | 20 ms |
| BM25 检索 | 1.3 ms | 2.3 ms |
| 重排（20 候选） | 601 ms | 935 ms |
| **端到端** | **621 ms** | **949 ms** |
| 端到端（候选降到 10） | 300 ms | 521 ms |

单进程吞吐约 1.6 QPS；重排是主要成本，见 `backend/README.md` 的调优建议。

### 语料规模

| 项目 | 数值 |
| --- | --- |
| 手册页数 | 206（PDF 内另有 1 页重复散页，已丢弃） |
| 文件篇数 | 28 |
| 知识块 | 586（一条一块，不跨条合并） |
| 检索单元 | 579（21 条超长条文按句拆分为子块，引用仍归并回整条） |
| 正文字数 | 75,150 |
| 问答条目 | 30（全部为 draft，需审核后发布） |
| 评测题 | 150 |

---

## 常见问题

**1. `pip install` 卡住不动、CPU 占满但没有任何进度**

某些受限环境不允许写系统临时目录，pip 会反复空转。把临时目录指到工作区内：

```powershell
$env:TEMP = "$PWD\.tmp"; $env:TMP = $env:TEMP
$env:PIP_NO_CACHE_DIR = "1"
```

**2. `ImportError: regex>=2025.10.22 is required ... but found regex==2023.10.3`**

装了 transformers 5.x。降到 4.56.2 并匹配 tokenizers：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps --ignore-installed transformers==4.56.2 tokenizers==0.22.2 "regex>=2024.11.6"
```

**3. `DLL load failed while importing _pywrap_tensorflow_internal`**

机器上装了坏的 TensorFlow，transformers 探测到就会尝试导入。本项目只用 torch，禁用即可（代码里已默认设置，手工运行时也加上）：

```powershell
$env:USE_TF = "0"; $env:USE_FLAX = "0"
```

**4. 模型下载中断（`ContentTooShortError` / 只下到几十 MB）**

CDN 会断流。`build_index.py` 重跑会跳过已下完的文件；若某个大文件始终下不完，改用手机热点，或下载完整后放到
`.cache/models/BAAI__bge-large-zh-v1.5/`（目录内需有 `config.json` 与权重文件）。

**5. 微信开发者工具黑屏 / 日志报 `WAAutoService.js not found in vendor contents map`**

基础库包没下完整（正常约 39 MB，残缺时只有几十 KB）。关闭工具后删除
`%LOCALAPPDATA%\微信开发者工具\User Data\<hash>\WeappVendor\<版本号>-<hash>`，重开工具让它重新下载。
换手机热点通常最快。

**6. `WXSS 文件编译错误 ... unexpected '\uFEFF' at pos 1`**

文件带了 UTF-8 BOM。`node scripts/check.js` 会检出所有带 BOM 的文件，用无 BOM 的方式重存即可（VS Code 右下角编码选 `UTF-8`）。

**7. 小程序显示「连不上问答服务」**

按顺序排查：后端是否在跑（`/v1/health` 能返回 JSON）→ 小程序 `utils/api.js` 的 `BASE_URL` 端口是否一致 →
开发者工具「详情 → 本地设置」中「不校验合法域名」是否勾选（项目已设 `urlCheck: false`）→ 控制台是否有 `request:fail`。

**7b. 回答是条文原文，不是整理过的话**

没配大模型密钥，或者调用失败后降级了。看 `/v1/health` 的 `llm`：`enabled` 是否为 `true`，`last_error` 写了什么。

**8. `无法加载文件 ... 因为在此系统上禁止运行脚本`**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1
```

**9. 端口 8000 被占用**

```powershell
..\knowledge_base\.venv\Scripts\python.exe run.py --port 8001
# 同时改小程序 miniprogram/utils/api.js 里的 BASE_URL
```

**10. 换模型后分数没变 / 报「索引指纹不匹配」**

索引与「模型 + 语料版本 + 切块参数」绑定。改配置后必须重建：

```powershell
.\.venv\Scripts\python.exe scripts\build_index.py --rebuild
```

---

## 数据来源与免责

- 语料来自《杭州电子科技大学学生手册》（学生处、教务处编，2017 年 9 月），共 206 页、28 篇文件。
- 手册前言写明「本手册内容与学校文件不符的，以学校文件为准」，因此涉及金额、比例、时效的条款一律标注需以现行文件核实。
- 手册只收录制度，**不包含办理窗口、电话与服务时段**；系统不编造这些信息，缺失处明确说明「以学校官网公布为准」。
- 该项目用于课程实践与技术验证，**不代表学校官方口径**。
- 仓库不含模型权重：bge-large-zh-v1.5、bge-reranker-v2-m3 由各自作者发布，请遵循其许可证。

## 为什么不提交模型

| 原因 | 说明 |
| --- | --- |
| 体积 | 两个模型合计 3.4 GB，超过 GitHub 单文件 100 MB 限制 |
| 可复现 | 模型公开可下载，`build_index.py` 会自动拉取 |
| 许可证 | 模型有自己的 License，不应由本仓转分发 |
| 更新成本 | 换模型不该产生几 GB 的历史 |

## 子文档

| 文档 | 内容 |
| --- | --- |
| [knowledge_base/README.md](knowledge_base/README.md) | 语料抽取的坑、切块规则、评测集构成、检索调优过程 |
| [knowledge_base/ARCHITECTURE.md](knowledge_base/ARCHITECTURE.md) | 检索层分层、索引指纹、为什么不用向量库 |
| [backend/README.md](backend/README.md) | 三项配置、接口、登录与身份、生成层的约束、两条检索路径 |
| [campus-assistant/README.md](campus-assistant/README.md) | 小程序页面、登录与身份、界面约定、检查方法 |
| [campus-assistant/DEMO.md](campus-assistant/DEMO.md) | 演示脚本与讲解要点 |

## 复现时间预算

| 阶段 | 耗时 |
| --- | --- |
| 建环境 | 5–10 分钟（取决于网络与是否已装 torch） |
| 下载模型 | 5–30 分钟（3.4 GB，视网络） |
| 建索引 | 约 40 秒（GPU） |
| 跑评测 | 5 分钟（含重排） |
| 起后端 + 小程序联调 | 10 分钟 |
| **合计** | **首次约 1 小时，之后启动只需 30 秒** |
