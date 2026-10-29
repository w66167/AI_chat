# -*- coding: utf-8 -*-
"""离线建索引：语料 → 检索单元 → 向量 → 带指纹的 .npz。

用法：
    python scripts/build_index.py                    # 建 config.json 里 active 的模型
    python scripts/build_index.py --model bge-m3
    python scripts/build_index.py --rebuild          # 强制重建（语料或配置变了）

幂等：指纹一致且索引存在时跳过，不会浪费时间重算 586 个块的向量。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kb import config, retriever  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', help='模型别名，默认取 config.json 的 embedder.active')
    ap.add_argument('--rebuild', action='store_true', help='强制重建')
    args = ap.parse_args()

    cfg = config.load()
    alias, spec = cfg.model(args.model)
    path = retriever.index_path(cfg, alias)
    fp = retriever.expected_fingerprint(cfg, alias, spec)

    if not args.rebuild and os.path.exists(path):
        from kb.index import Index
        try:
            idx = Index.load(path, fp)
            print('索引已存在且指纹一致，跳过：%s（%d 个单元）' % (path, idx.size))
            return 0
        except RuntimeError as e:
            print('索引失效，重建。原因：%s' % str(e).splitlines()[0])

    t0 = time.time()
    print('模型：%s (%s)' % (alias, spec['model_id']))
    print('下载/加载模型（首次会联网，之后走 .cache/models）……')
    index, saved, chunks = retriever.build_index(cfg, alias)
    cost = time.time() - t0
    print('完成：%d 个引用单元 → %d 个检索单元，维度 %d'
          % (len(chunks), index.size, index.vectors.shape[1]))
    print('耗时 %.1f 秒，索引 %s (%.1f MB)，指纹 %s'
          % (cost, saved, os.path.getsize(saved) / 2 ** 20, index.fingerprint))
    return 0


if __name__ == '__main__':
    sys.exit(main())
