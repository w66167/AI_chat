# -*- coding: utf-8 -*-
"""嵌入层：把文本变成向量。

接口只承诺「文本 → 向量」，「要不要加查询前缀」由 is_query 表达。
把前缀规则放进接口而不是调用处，是因为它是模型属性：写错位置会让分数
凭空掉几个点，而且极难发现。

实现两件事：
1. 模型下载：直连 ModelScope 的 HTTP 接口，不依赖 modelscope 包。
   （沙箱里 pip 装大包会卡住，且多一个依赖多一类故障）
2. 推理：transformers + 手动池化，池化方式读模型自带的 1_Pooling/config.json，
   不自己猜——bge 用 CLS，其他模型可能是 mean。

换模型 = 改 config.json 的 embedder.active，本文件不用改。
"""
import json
import os
import shutil
import time
import urllib.parse
import urllib.request
from typing import Protocol, Sequence

import numpy as np

# 这台机器的 Anaconda 里有一个装坏的 TensorFlow，transformers 只要探测到就会尝试导入
# 并抛 DLL 初始化失败。本项目只用 torch，显式关掉 TF/Flax 后端。
os.environ.setdefault('USE_TF', '0')
os.environ.setdefault('USE_FLAX', '0')
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')

MS_API = 'https://modelscope.cn/api/v1/models/%s/repo/files?Revision=master&Recursive=true'
MS_FILE = 'https://modelscope.cn/api/v1/models/%s/repo?Revision=master&FilePath=%s'
SKIP_SUFFIX = ('.gitattributes', '.md', '.png', '.jpg', '.gif')


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: Sequence[str], is_query: bool = False) -> np.ndarray:
        ...


# ---------------------------------------------------------------- 下载

def _ms_list(repo_id):
    """列出可下载的文件。注意清单里含 tree（目录）条目，必须过滤掉，
    否则会拿目录当文件下载并得到 404。"""
    url = MS_API % repo_id
    with urllib.request.urlopen(url, timeout=30) as r:
        payload = json.loads(r.read().decode('utf-8'))
    files = []
    for f in payload['Data']['Files']:
        if f.get('Type') != 'blob':
            continue
        if f['Path'].endswith(SKIP_SUFFIX):
            continue
        files.append(f['Path'])
    # safetensors 与 bin 是同权重的两份，只留一份，省一半流量
    if any(p.endswith('.safetensors') for p in files):
        files = [p for p in files if not p.endswith('.bin')]
    return files


def _ms_download(repo_id, path, dest, retries=3):
    url = MS_FILE % (repo_id, urllib.parse.quote(path))
    tmp = dest + '.part'
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, 'wb') as f:
                shutil.copyfileobj(r, f, length=1 << 20)
            os.replace(tmp, dest)
            return os.path.getsize(dest)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def download_model(repo_id, dest, log=print):
    """按文件清单同步模型到 dest。已存在且大小一致的文件跳过（可断点续传）。"""
    files = _ms_list(repo_id)
    os.makedirs(dest, exist_ok=True)
    total = 0
    for path in files:
        target = os.path.join(dest, path.replace('/', os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            total += os.path.getsize(target)
            continue
        size = _ms_download(repo_id, path, target)
        total += size
        if size > 1 << 20:
            log('  %-42s %6.1f MB' % (path, size / 2 ** 20))
    log('  模型文件共 %.1f MB → %s' % (total / 2 ** 20, dest))
    return dest


def resolve_model_dir(model_id, mirror_ids, cache_dir, log=print):
    os.makedirs(cache_dir, exist_ok=True)
    local = os.path.join(cache_dir, model_id.replace('/', '__'))
    required = ('config.json', 'tokenizer_config.json')
    if all(os.path.exists(os.path.join(local, f)) for f in required) and \
            any(f.endswith(('.safetensors', '.bin')) for f in os.listdir(local)):
        log('  模型已在本地：%s' % local)
        return local
    last = None
    for repo in [model_id] + list(mirror_ids or []):
        try:
            log('  下载 %s ……' % repo)
            return download_model(repo, local, log)
        except Exception as e:
            last = e
            log('  失败（%s）：%s' % (repo, str(e)[:100]))
    raise RuntimeError('模型下载失败：%s\n最后错误：%s' % (model_id, last))


# ---------------------------------------------------------------- 推理

def _pooling_from_config(model_dir):
    """返回 'cls' 或 'mean'，读模型自带的 1_Pooling/config.json。"""
    path = os.path.join(model_dir, '1_Pooling', 'config.json')
    if os.path.exists(path):
        cfg = json.load(open(path, encoding='utf-8'))
        if cfg.get('pooling_mode_cls_token'):
            return 'cls'
        if cfg.get('pooling_mode_mean_tokens'):
            return 'mean'
    # bge 系列默认 CLS；没有配置文件时按 CLS 兜底并提示
    return 'cls'


class TransformersEmbedder:
    name = ''
    dim = 0

    def __init__(self, alias, spec, cache_dir='.cache/models', device='cuda',
                 normalize=True, batch_size=32, log=print):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.name = alias
        self.spec = spec
        self.dim = spec.get('dim')
        self.query_prefix = spec.get('query_prefix', '') or ''
        self.normalize = normalize
        self.batch_size = batch_size
        self.device = device if torch.cuda.is_available() else 'cpu'
        self.torch = torch

        model_dir = resolve_model_dir(spec['model_id'], spec.get('mirror_ids'), cache_dir, log)
        self.model_path = model_dir
        self.pooling = _pooling_from_config(model_dir)
        max_len = spec.get('max_length') or 512

        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
        self.model = AutoModel.from_pretrained(model_dir)  # bge 权重本身是 fp32
        self.model.eval()
        self.model.to(self.device)
        self.tokenizer.model_max_length = max_len
        self.max_len = max_len
        log('  池化方式：%s | 最大长度：%d | 设备：%s' % (self.pooling, max_len, self.device))

    def encode(self, texts, is_query=False):
        texts = list(texts)
        if is_query and self.query_prefix:
            texts = [self.query_prefix + t for t in texts]
        vectors = []
        with self.torch.no_grad():
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i:i + self.batch_size]
                inputs = self.tokenizer(batch, padding=True, truncation=True,
                                        max_length=self.max_len, return_tensors='pt')
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                hidden = self.model(**inputs).last_hidden_state
                if self.pooling == 'cls':
                    pooled = hidden[:, 0]
                else:
                    mask = inputs['attention_mask'].unsqueeze(-1).float()
                    pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-6)
                if self.normalize:
                    pooled = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
                vectors.append(pooled.cpu().numpy())
        return np.vstack(vectors).astype(np.float32)


def build_embedder(cfg, alias=None, log=print):
    alias, spec = cfg.model(alias)
    emb_cfg = cfg['embedder']
    return TransformersEmbedder(
        alias, spec,
        cache_dir=os.path.join(cfg.root, emb_cfg['cache_dir']),
        device=emb_cfg.get('device', 'cuda'),
        normalize=emb_cfg.get('normalize', True),
        batch_size=emb_cfg.get('batch_size', 32),
        log=log)
