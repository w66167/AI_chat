# -*- coding: utf-8 -*-
"""后端入口（标准库 HTTP 服务）。

为什么不用 FastAPI：这台机器上 pip 装 FastAPI 会卡死（沙箱内 pip 反复空转，
前后试了四次，耗时反而超过写代码本身）。接口契约、字段校验、错误格式与
schemas.py 完全一致，换成 FastAPI 时只需把 server.py 的路由映射过去，
上层（小程序）一行都不用改。

启动：
    & "知识库\\.venv\\Scripts\\python.exe" run.py --port 8000
"""
import argparse
import json
import os
import sys

from app.server import make_server


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8000)
    args = ap.parse_args()

    httpd = make_server(args.host, args.port)
    print('API 已启动：http://%s:%d' % (args.host, args.port))
    print('  健康检查  GET  /v1/health')
    print('  问答      POST /v1/ask        {"question": "宿舍几点熄灯"}')
    print('  反馈      POST /v1/feedback   {"session_id": "...", "message_id": "...", "resolved": true}')
    print('  接口说明  GET  /docs')
    print('模型预热中（约 12 秒，期间 /v1/health 返回 status=warming）……', flush=True)

    from app import deps
    deps.warmup_async()

    print('按 Ctrl+C 停止。')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
