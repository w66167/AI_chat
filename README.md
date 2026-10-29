# 校园智能问答系统

把《杭州电子科技大学学生手册》（206 页、28 篇文件）变成**可检索、可追溯、会拒答**的问答服务，前端是一个微信小程序。

回答不是模型瞎编的，而是从手册原文里检索出来的，并且**每条都带文件名、条号和页码**；查不到就明说查不到，并给出该去哪个官方渠道问。

---

## 效果

```
问：宿舍几点熄灯？
答：严格遵守学校规定的作息时间……自主熄灯时间 22:50、统一熄灯 23:00……
    夏季、冬季通宵供电。
出处：《杭州电子科技大学学生住宿管理规定》第二十二条 · 第174页
耗时：1.0 秒

问：图书馆几点开门？
答：当前知识库（学生手册 2017 年版）里没有足够可靠的依据回答这个问题，我不做推测。
耗时：0.7 秒

问：帮我报修一下宿舍漏水。
答：这里只提供制度和流程说明，不代为受理、不派发工单、不承诺办理结果。
耗时：0.002 秒   ← 越界请求直接拦截，不进检索
```

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
│  ├─ app/answer.py             策略层：越界/澄清/拒答/作答
│  ├─ app/server.py             HTTP 路由
│  └─ tests/                    冒烟测试、策略评测、小程序契约测试
└─ campus-assistant/            微信小程序
   ├─ miniprogram/pages/        首页 / 问答 / 我的 / 指南 / 详情 / 工作台
   ├─ miniprogram/utils/api.js  唯一的联网入口
   └─ scripts/check.js          静态检查（语法、BOM、联网规则、离线回退）
```

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

看到「模型预热完成」约需 25–30 秒（预热期间 `/v1/health` 返回 `status=warming`）。

```powershell
# 另开一个窗口验证
curl.exe -s http://127.0.0.1:8000/v1/health
curl.exe -s -X POST http://127.0.0.1:8000/v1/ask -H "Content-Type: application/json" -d "{\"question\":\"宿舍几点熄灯\"}"
```

也可以直接打开 <http://127.0.0.1:8000/docs> 看接口说明。

### 第 7 步：跑小程序

1. 微信开发者工具 → 导入项目
2. 目录选 **`campus-assistant`**（不是里面的 `miniprogram`）
3. AppID 选「测试号」或游客模式；后端服务选「不使用云服务」
4. 点「编译」

首页右上角应显示「**● 在线**」。如果显示「本地」，说明没连上后端——小程序会自动回退到本机 20 条示例知识，页面不会白屏。

改完代码想先做静态检查，不打开工具也行：

```powershell
cd campus-assistant
node scripts/check.js          # 语法、BOM、联网规则、离线回退
python scripts/check-wxml.py   # WXML 标签闭合（可选）
```

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

**7. 小程序一直显示「本地」而不是「在线」**

按顺序排查：后端是否在跑（`/v1/health` 能返回 JSON）→ `model_loaded` 是否为 `true`（`warming` 表示还在加载）→
开发者工具「详情 → 本地设置」中「不校验合法域名」是否勾选（项目已设 `urlCheck: false`）→ 控制台是否有 `request:fail`。

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
| [backend/README.md](backend/README.md) | API 契约、策略层判断顺序、阈值标定依据、延迟优化 |
| [campus-assistant/README.md](campus-assistant/README.md) | 小程序界面结构、在线/离线双模式、字段映射 |
| [campus-assistant/DEMO.md](campus-assistant/DEMO.md) | 5 分钟演示脚本与讲解要点 |

## 复现时间预算

| 阶段 | 耗时 |
| --- | --- |
| 建环境 | 5–10 分钟（取决于网络与是否已装 torch） |
| 下载模型 | 5–30 分钟（3.4 GB，视网络） |
| 建索引 | 约 40 秒（GPU） |
| 跑评测 | 5 分钟（含重排） |
| 起后端 + 小程序联调 | 10 分钟 |
| **合计** | **首次约 1 小时，之后启动只需 30 秒** |
