# -*- coding: utf-8 -*-
"""重排：把候选条文按「与问题的相关性」重新打分。

为什么需要它：诊断显示 gold 条文在 Top-10 里占 90%，但 Top-3 只有 74.5%——
说明双塔向量模型「能找到但排不准」。交叉编码器把问题和条文拼在一起送入模型，
精度显著高于双塔，代价是只能对少量候选做（所以作用是重排，不是召回）。

模型同样通过 ModelScope 直连下载，池化/标签方式由模型自带的分类头决定。
"""
import os

import numpy as np

from .embedder import resolve_model_dir


class CrossEncoderReranker:
    def __init__(self, spec, cache_dir='.cache/models', device='cuda',
                 batch_size=16, max_length=512, log=print):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.spec = spec
        self.batch_size = batch_size
        self.max_length = max_length
        self.device = device if torch.cuda.is_available() else 'cpu'

        model_dir = resolve_model_dir(spec['model_id'], spec.get('mirror_ids'), cache_dir, log)
        self.model_path = model_dir
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        self.model.eval()
        self.model.to(self.device)
        log('  重排模型就绪：%s | 设备：%s' % (os.path.basename(model_dir), self.device))

    def rerank(self, query, pairs, top_k=3):
        """pairs: [(chunk_id, text)]；返回 [(chunk_id, score)] 降序。"""
        if not pairs:
            return []
        ids = [p[0] for p in pairs]
        texts = [p[1] for p in pairs]
        scores = []
        with self.torch.no_grad():
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i:i + self.batch_size]
                inputs = self.tokenizer([query] * len(batch), batch, padding=True,
                                        truncation=True, max_length=self.max_length,
                                        return_tensors='pt')
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                logits = self.model(**inputs).logits.view(-1).float()
                scores.extend(logits.cpu().numpy().tolist())
        order = np.argsort(-np.asarray(scores))[:top_k]
        return [(ids[i], float(scores[i])) for i in order]


def build_reranker(cfg, log=print):
    spec = cfg.get('reranker') or {}
    if not spec.get('enabled'):
        return None
    return CrossEncoderReranker(spec, cache_dir=os.path.join(cfg.root, cfg['embedder']['cache_dir']),
                                device=cfg['embedder'].get('device', 'cuda'),
                                batch_size=spec.get('batch_size', 16),
                                max_length=spec.get('max_length', 512), log=log)
