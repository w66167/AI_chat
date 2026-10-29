# -*- coding: utf-8 -*-
"""把 handbook_qa.json 导出为小程序可直接 require 的知识模块。

默认只导出 draft 之外的状态？不。默认全部导出，但保留 status 字段：
小程序 store.js 的 getKnowledge() 只取 status === 'published'，
因此导出后不会自动出现在问答里，必须先走审核发布流程。

    python export_miniprogram.py                 # 导出全部（含 draft）
    python export_miniprogram.py --publish       # 演示用：把所有条目置为 published
"""
import argparse
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
OUT = os.path.join(DATA, 'handbook.js')


def js(value):
    return json.dumps(value, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--publish', action='store_true')
    args = ap.parse_args()

    kb = json.load(open(os.path.join(DATA, 'handbook_qa.json'), encoding='utf-8'))
    items = []
    for e in kb['entries']:
        items.append({
            'id': e['id'],
            'category': e['category'],
            'title': e['title'],
            'aliases': e['aliases'],
            'answer': e['answer'],
            'steps': e['steps'],
            'channel': e['channel'],
            'source': e['source'],
            'scope': e['scope'],
            'version': e['version'],
            'updatedAt': e['updatedAt'],
            'status': 'published' if args.publish else e['status'],
            'isDemo': False,
            'handbookRef': e['handbook_ref'],
        })

    lines = [
        '// 由 knowledge_base/scripts/export_miniprogram.py 生成，请勿手工编辑。',
        '// 出处：《杭州电子科技大学学生手册》（2017年9月，206页，28篇文件）。',
        '// 条目状态为 %s；小程序只检索 status === "published" 的知识。' % (
            'published（演示用，未经人工审核）' if args.publish else 'draft（待审核）'),
        'const categories = %s;' % js(kb['categories']),
        'const knowledge = %s;' % js(items),
        'const meta = %s;' % js(kb['meta']),
        'module.exports = { categories, knowledge, meta };',
    ]
    open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('已导出 %d 条到 %s（状态：%s）' % (len(items), OUT,
                                       'published' if args.publish else 'draft'))


if __name__ == '__main__':
    main()
