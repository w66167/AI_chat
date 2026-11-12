# -*- coding: utf-8 -*-
"""依赖装配：检索器全局只建一次。

两条检索路径，接口相同（search / chunks）：
  vector   向量 + BM25 融合 + 重排。准（Top-3 89%），但要 torch、模型权重、建好的索引，占 3.5 GB 显存。
  lexical  正文 + 标题 + 常见问法的关键词检索。只用标准库，任何机器都能跑（Top-3 77%，Top-5 84%）。

backend = auto 时先试 vector，装配失败（没装环境、没建索引、没有模型）就退到 lexical 并记下原因，
健康检查里能看到当前走的是哪条。这样后端在一台普通云服务器上也能启动，不会因为没有显卡整个不可用。

懒加载的原因：模型加载要 12 秒，每个请求重建既慢又会把显存打爆。启动时另开线程预热。
"""
import threading

_lock = threading.Lock()
_state = {'retriever': None, 'cfg': None, 'chunks': None, 'ready': False, 'error': '',
          'mode': '', 'fallback_reason': ''}


def get_config():
    if _state['cfg'] is None:
        from .config import load
        _state['cfg'] = load()
    return _state['cfg']


def _build_vector(cfg):
    from kb.hybrid import build_retrievers
    return build_retrievers(cfg.kb, ['hybrid+rerank'], log=_log)['hybrid+rerank']


def _build_lexical(cfg):
    import json
    import os

    from kb.corpus import load_chunks
    from kb.lexical import FieldedBM25Retriever, faq_map
    path = cfg.kb['corpus']['chunks_path']
    if not os.path.isabs(path):
        path = os.path.join(cfg.kb.root, path)
    chunks = load_chunks(path)
    try:
        with open(os.path.join(cfg.kb.root, 'data', 'handbook_qa.json'), encoding='utf-8') as f:
            entries = json.load(f)['entries']
    except (OSError, ValueError, KeyError):
        entries = []
    return FieldedBM25Retriever({c.id: c for c in chunks}, chunks, faq_map(entries, chunks),
                                exclude_articles=cfg.kb['corpus'].get('exclude_articles') or ())


def get_retriever():
    """返回检索器；首次调用时装配。向量路径不可用时按配置退到关键词路径。"""
    if _state['retriever'] is None:
        with _lock:
            if _state['retriever'] is None:
                try:
                    cfg = get_config()
                    backend = (cfg.get('search') or {}).get('backend', 'auto')
                    if backend in ('auto', 'vector'):
                        try:
                            _state['retriever'] = _build_vector(cfg)
                            _state['mode'] = 'vector'
                        except Exception as e:
                            if backend == 'vector':
                                raise
                            _state['fallback_reason'] = '%s: %s' % (type(e).__name__, str(e)[:160])
                            _log('向量检索不可用（%s），改用关键词检索' % _state['fallback_reason'])
                    if _state['retriever'] is None:
                        _state['retriever'] = _build_lexical(cfg)
                        _state['mode'] = 'lexical'
                    _state['chunks'] = _state['retriever'].chunks
                    _state['ready'] = True
                    _state['error'] = ''
                except Exception as e:      # 记录失败原因，健康检查要能看见
                    _state['error'] = str(e)[:200]
                    raise
    return _state['retriever']


def get_chunks():
    get_retriever()
    return _state['chunks']


def is_ready():
    """模型是否已加载。健康检查用它判断，避免健康检查自己触发 12 秒加载。"""
    return _state['ready']


def status():
    return {'ready': _state['ready'], 'error': _state['error'],
            'chunks': len(_state['chunks']) if _state['chunks'] else 0,
            'mode': _state['mode'], 'fallback_reason': _state['fallback_reason']}


def warmup_async():
    """启动时后台预热。否则第一次请求要等模型加载，小程序 8 秒超时会误判服务不可用。"""
    def run():
        try:
            get_retriever()
            _log('检索器就绪（%s）' % _state['mode'])
        except Exception as e:
            _log('检索器装配失败：%s' % e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _log(msg):
    print(msg, flush=True)


_llm = {'errors': 0, 'last_error': ''}


def note_llm_error(message):
    """记下最近一次生成失败的原因，健康检查里能看到（密钥错、超时、输出不合规）。"""
    _llm['errors'] += 1
    _llm['last_error'] = str(message)[:160]
    _log('生成降级：%s' % _llm['last_error'])


def llm_errors():
    return dict(_llm)
