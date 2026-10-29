# -*- coding: utf-8 -*-
"""环境自检：一条命令定位「跑不起来」的原因。

    python scripts/doctor.py            # 快速检查（不加载重排模型）
    python scripts/doctor.py --full     # 连重排模型一起加载，跑一次完整问答

每项失败都给出具体修法，不用猜。
"""
import argparse
import importlib.util
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)

ok_all = True


def report(name, ok, detail='', fix=''):
    global ok_all
    mark = 'OK  ' if ok else 'FAIL'
    print('[%s] %-28s %s' % (mark, name, detail))
    if not ok:
        ok_all = False
        if fix:
            print('        修法：%s' % fix)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true')
    args = ap.parse_args()

    print('解释器：%s' % sys.executable)
    print('项目根：%s\n' % WS)

    # 1. 依赖
    for mod, label, fix in [
            ('torch', 'torch', '用 .venv 里的 python 运行'),
            ('transformers', 'transformers', r'& "知识库\.venv\Scripts\python.exe" -m pip install transformers'),
            ('numpy', 'numpy', 'pip install numpy')]:
        spec = importlib.util.find_spec(mod)
        report('依赖 ' + label, bool(spec), '' if spec else '未安装', fix)

    if importlib.util.find_spec('torch'):
        import torch
        report('CUDA 可用', torch.cuda.is_available(),
               torch.cuda.get_device_name(0) if torch.cuda.is_available() else '将回退到 CPU',
               '确认安装了显卡驱动；CPU 也能跑，只是慢')

    venv_py = os.path.join(WS, '.venv', 'Scripts', 'python.exe')
    report('使用项目 venv', os.path.normcase(sys.executable) == os.path.normcase(venv_py),
           venv_py, 'Anaconda 的 python 缺 transformers，必须用 .venv 里的')

    # 2. 配置与语料
    try:
        from kb import config
        cfg = config.load()
        report('config.json 可解析', True, '模型=%s' % cfg['embedder']['active'])
    except Exception as e:
        report('config.json 可解析', False, str(e)[:60], '检查 JSON 语法（多余逗号/中文引号）')
        return 1

    chunks_path = cfg['corpus']['chunks_path']
    if not os.path.isabs(chunks_path):
        chunks_path = os.path.join(cfg.root, chunks_path)
    report('语料文件存在', os.path.exists(chunks_path), chunks_path)

    # 3. 模型缓存
    cache = os.path.join(cfg.root, cfg['embedder']['cache_dir'])
    for alias in [cfg['embedder']['active']] + (['bge-reranker-v2-m3'] if args.full else []):
        spec = (cfg['embedder']['models'].get(alias)
                or (cfg.get('reranker') if alias == 'bge-reranker-v2-m3' else None) or {})
        mid = spec.get('model_id', '')
        d = os.path.join(cache, mid.replace('/', '__')) if mid else ''
        size = 0
        if d and os.path.isdir(d):
            size = sum(os.path.getsize(os.path.join(r, f))
                       for r, _, fs in os.walk(d) for f in fs)
        report('模型 %s' % alias, size > 100 * 2 ** 20,
               '%.0f MB' % (size / 2 ** 20),
               '首次运行会自动下载；下载失败就删掉该目录重跑')

    # 4. 索引指纹
    try:
        from kb import retriever
        alias, spec = cfg.model()
        path = retriever.index_path(cfg, alias)
        fp = retriever.expected_fingerprint(cfg, alias, spec)
        from kb.index import Index
        idx = Index.load(path, fp)
        report('索引指纹一致', True, '%d 个单元，指纹 %s' % (idx.size, idx.fingerprint))
    except Exception as e:
        report('索引指纹一致', False, str(e).splitlines()[0][:80],
               'python scripts/build_index.py --rebuild')

    # 5. 端到端
    if args.full:
        from kb.hybrid import build_retrievers
        try:
            rs = build_retrievers(cfg, ['hybrid+rerank'])
            r = rs['hybrid+rerank']
            top = r.search('宿舍几点熄灯', k=3)
            report('完整问答链路', bool(top), 'top1=%s' % (top[0][0] if top else '-'))
        except Exception as e:
            report('完整问答链路', False, str(e)[:80], '看上面的具体报错')

    print('\n结论：%s' % ('全部通过' if ok_all else '有失败项，按上面「修法」处理'))
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
