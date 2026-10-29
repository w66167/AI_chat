# -*- coding: utf-8 -*-
"""依赖装配：检索器与重排模型全局只建一次。

懒加载的原因：模型加载要 12 秒、占 3.5 GB 显存，每个请求重建既慢又会把显存打爆。
启动时另开线程预热，避免第一次请求超时。
"""
import threading

_lock = threading.Lock()
_state = {'retriever': None, 'cfg': None, 'chunks': None, 'ready': False, 'error': ''}


def get_config():
    if _state['cfg'] is None:
        from .config import load
        _state['cfg'] = load()
    return _state['cfg']


def get_retriever():
    """返回 hybrid+rerank 检索器；首次调用时加载模型。"""
    if _state['retriever'] is None:
        with _lock:
            if _state['retriever'] is None:
                try:
                    from kb.hybrid import build_retrievers
                    cfg = get_config()
                    rs = build_retrievers(cfg.kb, ['hybrid+rerank'], log=_log)
                    _state['retriever'] = rs['hybrid+rerank']
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
            'chunks': len(_state['chunks']) if _state['chunks'] else 0}


def warmup_async():
    """启动时后台预热。否则第一次请求要等模型加载，小程序 8 秒超时会误判服务不可用。"""
    def run():
        try:
            get_retriever()
            _log('模型预热完成')
        except Exception as e:
            _log('模型预热失败：%s' % e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _log(msg):
    print(msg, flush=True)
