# -*- coding: utf-8 -*-
"""把知识库注册表（data/libraries.json）导出为小程序可直接 require 的数据模块。

为什么要有这个脚本：
    知识库注册表是「后端按身份路由检索」和「小程序按身份展示来源」共用的唯一事实来源。
    小程序不能 require JSON，所以这里生成一份 JS 数据模块；后端直接读 JSON。
    两边一旦不一致，就会出现「后端说查了学生手册、前端显示公开指南」这种错。

用法：
    python export_libraries.py            # 生成 campus-assistant/miniprogram/data/libraries.js
    python export_libraries.py --check    # 只校验是否已同步，不同步则退出码 1（给测试用）
"""
import argparse
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, 'data', 'libraries.json')
OUT = os.path.join(os.path.dirname(BASE), 'campus-assistant', 'miniprogram', 'data', 'libraries.js')


def js(value):
    return json.dumps(value, ensure_ascii=False)


def render(registry):
    lines = [
        '// 由 knowledge_base/scripts/export_libraries.py 生成，请勿手工编辑。',
        '// 唯一数据源：knowledge_base/data/libraries.json（后端 backend/app/libraries.py 直接读它）。',
        '// 重新生成：python knowledge_base/scripts/export_libraries.py',
        'const identities = %s;' % js(registry['identities']),
        'const libraries = %s;' % js(registry['libraries']),
        'const meta = %s;' % js({'version': registry.get('version', 1), 'source': 'knowledge_base/data/libraries.json'}),
        'module.exports = { identities, libraries, meta };',
        '',
    ]
    return '\n'.join(lines)


def write_text(path, text):
    # 统一 LF：git 在 Windows 上检出时会转成 CRLF，这里不引入第二套行尾规则。
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只校验小程序端是否与注册表同步')
    args = ap.parse_args()

    with open(SRC, encoding='utf-8') as f:
        registry = json.load(f)
    text = render(registry)

    if args.check:
        if not os.path.exists(OUT):
            print('未同步：缺少 %s，请运行 export_libraries.py' % OUT)
            return 1
        with open(OUT, encoding='utf-8') as f:
            current = f.read()
        if current.replace('\r\n', '\n') != text:
            print('未同步：%s 与 libraries.json 不一致，请运行 export_libraries.py' % OUT)
            return 1
        print('已同步：%d 个身份、%d 个知识库' % (len(registry['identities']), len(registry['libraries'])))
        return 0

    write_text(OUT, text)
    print('已生成 %d 个身份、%d 个知识库 → %s' % (
        len(registry['identities']), len(registry['libraries']), OUT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
