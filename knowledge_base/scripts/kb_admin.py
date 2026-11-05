# -*- coding: utf-8 -*-
"""知识维护与审核（管理端 CLI）。

为什么单独做成命令行工具：
    「知识维护人员 / 知识审核员」是对系统负责、不是使用系统的角色，不该出现在用户端小程序里。
    但需求文档 FR-25（知识维护）、FR-26（字段校验）、FR-27（审核与状态）、FR-34（操作审计）
    以及 2.1 节「知识作者不能审核本人版本」这些要求依然要有人接住，所以把这一层放在管理端。
    用户端小程序只保留游客 / 学生 / 教师三种使用者身份。

数据文件（都在 knowledge_base/data/ 下）：
    kb_drafts.json     草稿区：draft → pending → rejected / approved
    kb_published.json  已发布知识（版本号在此递增）
    kb_audit.jsonl     审计日志，只追加，记录操作主体/动作/对象/时间/结果/原因

用法：
    python kb_admin.py draft  --actor maintainer --kb public-guide --category 后勤 \
        --title "食堂遗失物品怎么找回？" --answer "……" --source "课题演示资料 · 后勤办事指南" \
        --channel "食堂服务台" --scope "演示校区 · 全体师生" --long-term
    python kb_admin.py submit --actor maintainer --id draft-xxxx
    python kb_admin.py review --actor reviewer --id draft-xxxx --approve
    python kb_admin.py review --actor reviewer --id draft-xxxx --reject --reason "请补充办理步骤"
    python kb_admin.py list --status pending
    python kb_admin.py log --limit 10
    python kb_admin.py selftest          # 不需要任何外部依赖，验证全部规则
"""
import argparse
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
REGISTRY = os.path.join(DATA, 'libraries.json')

REQUIRED_FIELDS = ('kbId', 'title', 'category', 'answer', 'source', 'channel', 'scope')
FIELDS = ('kbId', 'title', 'category', 'aliases', 'answer', 'steps', 'channel', 'source',
          'article', 'page', 'scope', 'effectiveFrom', 'effectiveTo', 'longTerm')


# ---------------------------------------------------------------- 注册表

def registry():
    with open(REGISTRY, encoding='utf-8') as f:
        return json.load(f)


def admin_roles():
    """管理端角色（app === false）：知识维护人员与知识审核员。"""
    return {item['id']: item for item in registry()['identities'] if item.get('app') is False}


def library_ids():
    return [item['id'] for item in registry()['libraries']]


# ---------------------------------------------------------------- 存储

class Store:
    """知识数据存储。

    root=None 时纯内存运行（自测用），完全不碰文件系统——自测要在任何环境下都能跑。
    """

    def __init__(self, root=None):
        self.root = root
        self.memory = root is None
        self._drafts = [] if self.memory else self._read('kb_drafts.json', 'drafts')
        self._published = [] if self.memory else self._read('kb_published.json', 'items')
        self._audit = []

    def _read(self, name, key):
        path = os.path.join(self.root, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as f:
            return json.load(f)[key]

    def _write(self, name, key, items):
        if self.memory:
            return
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, name), 'w', encoding='utf-8') as f:
            json.dump({'version': 1, key: items}, f, ensure_ascii=False, indent=2)
            f.write('\n')

    def drafts(self):
        return self._drafts

    def published(self):
        return self._published

    def save_drafts(self, items):
        self._drafts = items
        self._write('kb_drafts.json', 'drafts', items)

    def save_published(self, items):
        self._published = items
        self._write('kb_published.json', 'items', items)

    def audit(self, actor, action, target, result, reason=''):
        """审计只追加：记录操作主体、动作、对象、时间、结果、原因（FR-34）。"""
        record = {'time': time.strftime('%Y-%m-%dT%H:%M:%S'), 'actor': actor, 'action': action,
                  'target': target, 'result': result, 'reason': reason}
        self._audit.append(record)
        if not self.memory:
            os.makedirs(self.root, exist_ok=True)
            with open(os.path.join(self.root, 'kb_audit.jsonl'), 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        return record

    def log(self, limit=20):
        if self.memory:
            return self._audit[-limit:]
        path = os.path.join(self.root, 'kb_audit.jsonl')
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as f:
            lines = [json.loads(line) for line in f if line.strip()]
        return lines[-limit:]


# ---------------------------------------------------------------- 业务规则

def require_role(actor, expected):
    roles = admin_roles()
    if actor not in roles:
        raise ValueError('未知的管理端主体：%s（可选：%s）' % (actor, '、'.join(roles)))
    if expected and actor != expected:
        name = roles[actor]['name']
        raise PermissionError('%s 不能执行该操作（需要%s）。' % (name, roles[expected]['name']))


def validate(fields):
    """FR-26：不完整不得提交；失效时间须晚于生效时间；长期有效须显式标记。"""
    missing = [key for key in REQUIRED_FIELDS if not str(fields.get(key) or '').strip()]
    if missing:
        raise ValueError('缺少必填字段：%s' % '、'.join(missing))
    if fields['kbId'] not in library_ids():
        raise ValueError('知识库不存在：%s' % fields['kbId'])
    start, end = fields.get('effectiveFrom') or '', fields.get('effectiveTo') or ''
    if fields.get('longTerm'):
        if end:
            raise ValueError('标记为长期有效时不能同时填写失效时间。')
    else:
        if not end:
            raise ValueError('必须填写失效时间，或显式标记为长期有效。')
        if not start:
            raise ValueError('填写失效时间时必须同时填写生效时间。')
        if end <= start:
            raise ValueError('失效时间必须晚于生效时间。')


def create_draft(store, actor, fields, draft_id=None, target_id=''):
    require_role(actor, None)
    if actor not in ('maintainer',):
        raise PermissionError('只有知识维护人员能起草或修订知识。')
    validate(fields)
    drafts = store.drafts()
    existing = next((d for d in drafts if d['id'] == draft_id), None) if draft_id else None
    if draft_id and not existing:
        raise ValueError('草稿不存在：%s' % draft_id)
    if existing:
        # 已提交的版本冻结；驳回后回到可修改状态（2.3 节），改完状态回到 draft
        if existing['status'] not in ('draft', 'rejected'):
            raise ValueError('该草稿状态为 %s，已提交的版本不能直接改写，请复制为新草稿。' % existing['status'])
        if existing['author'] != actor:
            raise ValueError('只能编辑本人未提交的草稿。')
    target = None
    if target_id:
        target = next((item for item in store.published() if item['id'] == target_id), None)
        if not target:
            raise ValueError('要修订的知识不存在：%s' % target_id)
        if not existing and any(d.get('targetId') == target_id and d['status'] in ('draft', 'pending', 'rejected') for d in drafts):
            raise ValueError('这条知识已有未完成的修订，请先处理已有草稿。')
    base = existing['id'] if existing else (draft_id or 'draft-%d' % int(time.time() * 1000))
    draft = {
        'id': base, 'targetId': target['id'] if target else '', 'status': 'draft',
        'author': actor, 'authorName': admin_roles()[actor]['name'],
        'baseVersion': existing['baseVersion'] if existing else (target['version'] if target else 0),
        'reason': '', 'createdAt': time.strftime('%Y-%m-%d'),
        'title': fields['title'].strip(), 'category': fields['category'].strip(),
        'aliases': [a.strip() for a in (fields.get('aliases') or '').split(',') if a.strip()],
        'answer': fields['answer'].strip(), 'steps': [s.strip() for s in (fields.get('steps') or '').split('\n') if s.strip()],
        'channel': fields['channel'].strip(), 'source': fields['source'].strip(),
        'article': (fields.get('article') or '').strip(), 'page': int(fields.get('page') or 0),
        'scope': fields['scope'].strip(), 'kbId': fields['kbId'],
        'effectiveFrom': fields.get('effectiveFrom') or '', 'effectiveTo': fields.get('effectiveTo') or '',
        'longTerm': bool(fields.get('longTerm')),
    }
    if existing:
        drafts[drafts.index(existing)] = draft
        action = '修改草稿'
    else:
        drafts.insert(0, draft)
        action = '新建草稿'
    store.save_drafts(drafts)
    store.audit(actor, action, draft['id'], 'ok')
    return draft


def submit_draft(store, actor, draft_id):
    require_role(actor, 'maintainer')
    drafts = store.drafts() if hasattr(store, 'drafts') else store
    draft = next((d for d in drafts if d['id'] == draft_id), None)
    if not draft:
        raise ValueError('草稿不存在：%s' % draft_id)
    if draft['author'] != actor:
        raise PermissionError('只能提交本人起草的知识。')
    if draft['status'] not in ('draft', 'rejected'):
        raise ValueError('状态为 %s 的草稿不能提交。' % draft['status'])
    validate(draft)
    draft['status'] = 'pending'
    draft['reason'] = ''
    store.save_drafts(drafts)
    store.audit(actor, '提交审核', draft_id, 'ok')
    return draft


def review_draft(store, actor, draft_id, approve, reason=''):
    """FR-27：禁止作者自审；驳回必须给可执行的修改原因；发布失败不能返回成功。"""
    require_role(actor, 'reviewer')
    drafts = store.drafts()
    draft = next((d for d in drafts if d['id'] == draft_id), None)
    if not draft:
        raise ValueError('审核单不存在：%s' % draft_id)
    if draft['status'] != 'pending':
        raise ValueError('该知识当前状态为 %s，不在待审核。' % draft['status'])
    if draft['author'] == actor:
        # 职责分离：作者不能审核自己参与编写的版本（2.1 节）
        raise PermissionError('不能审核自己起草的知识（职责分离）。')
    if not approve:
        if not str(reason or '').strip():
            raise ValueError('驳回必须填写可执行的修改原因。')
        draft['status'] = 'rejected'
        draft['reason'] = reason.strip()
        store.save_drafts(drafts)
        store.audit(actor, '驳回知识', draft_id, 'rejected', reason.strip())
        return draft
    published = store.published()
    target = next((item for item in published if item['id'] == draft['targetId']), None) if draft['targetId'] else None
    if draft['targetId'] and not target:
        raise ValueError('要修订的原知识已不存在。')
    if target and target['version'] != draft['baseVersion']:
        # 乐观锁：提交后版本被别人更新过，必须重新加载比较（2.5 节）
        raise ValueError('原知识版本已从 v%s 变为 v%s，请重新加载后再提交。' % (draft['baseVersion'], target['version']))
    item = {
        'id': target['id'] if target else 'kb-%d' % int(time.time() * 1000),
        'kbId': draft['kbId'], 'title': draft['title'], 'category': draft['category'],
        'aliases': draft['aliases'], 'answer': draft['answer'], 'steps': draft['steps'],
        'channel': draft['channel'], 'source': draft['source'], 'article': draft['article'],
        'page': draft['page'], 'scope': draft['scope'],
        'effectiveFrom': draft['effectiveFrom'], 'effectiveTo': draft['effectiveTo'],
        'longTerm': draft['longTerm'], 'status': 'published',
        'version': (target['version'] + 1) if target else 1,
        'updatedAt': time.strftime('%Y-%m-%d'),
    }
    if target:
        published[published.index(target)] = item
    else:
        published.insert(0, item)
    draft['status'] = 'approved'
    draft['publishedVersion'] = item['version']
    store.save_published(published)
    store.save_drafts(drafts)
    store.audit(actor, '审核发布 v%d' % item['version'], item['id'], 'published')
    return item


# ---------------------------------------------------------------- 自测

def selftest():
    """不依赖任何外部环境，把 FR-25/26/27/34 的规则跑一遍。

    纯内存运行：不写 knowledge_base/data/，也不依赖临时目录权限。
    """
    store = Store(None)
    if True:
        base = {'kbId': 'public-guide', 'category': '后勤', 'title': '食堂遗失物品怎么找回？',
                'answer': '演示答案', 'source': '课题演示资料 · 后勤办事指南', 'channel': '食堂服务台',
                'scope': '演示校区 · 全体师生', 'longTerm': True}

        # 字段校验（FR-26）
        for broken, expect in [({**base, 'title': ''}, '必填'),
                               ({**base, 'kbId': 'nope'}, '知识库不存在'),
                               ({**base, 'longTerm': False, 'effectiveTo': ''}, '失效时间'),
                               ({**base, 'longTerm': False, 'effectiveFrom': '2026-01-01', 'effectiveTo': '2025-01-01'}, '晚于'),
                               ({**base, 'longTerm': True, 'effectiveTo': '2026-01-01'}, '长期有效')]:
            try:
                create_draft(store, 'maintainer', broken)
                raise AssertionError('应当拒绝：%s' % expect)
            except ValueError as e:
                assert expect in str(e), '错误信息不含「%s」：%s' % (expect, e)

        # 角色校验：审核员不能起草，维护人员不能审核
        for func, args, role in [(create_draft, (store, 'reviewer', base), 'reviewer'),
                                 (review_draft, (store, 'maintainer', 'x', True), 'maintainer')]:
            try:
                func(*args)
                raise AssertionError('应当拒绝越权：%s' % role)
            except PermissionError:
                pass

        draft = create_draft(store, 'maintainer', base)
        assert draft['status'] == 'draft'
        # 提交前不能审核
        try:
            review_draft(store, 'reviewer', draft['id'], True)
            raise AssertionError('未提交的草稿不应可审核')
        except ValueError:
            pass
        submit_draft(store, 'maintainer', draft['id'])
        # 已提交版本冻结，不能直接改写（FR-25）
        try:
            create_draft(store, 'maintainer', {**base, 'answer': '偷偷改'}, draft_id=draft['id'])
            raise AssertionError('已提交版本不应可改写')
        except ValueError:
            pass
        # 作者自审阻断（2.1 职责分离）
        author = store.drafts()[0]['author']
        store.drafts()[0]['author'] = 'reviewer'
        store.save_drafts(store.drafts())
        try:
            review_draft(store, 'reviewer', draft['id'], True)
            raise AssertionError('不应允许自审')
        except PermissionError:
            pass
        store.drafts()[0]['author'] = author
        store.save_drafts(store.drafts())
        # 驳回必须填原因
        try:
            review_draft(store, 'reviewer', draft['id'], False, '')
            raise AssertionError('驳回必须填原因')
        except ValueError:
            pass
        review_draft(store, 'reviewer', draft['id'], False, '请补充办理步骤')
        assert store.drafts()[0]['status'] == 'rejected'

        # 驳回后修改 → 重新提交 → 通过 → 发布 v1
        create_draft(store, 'maintainer', {**base, 'steps': '第一步\n第二步'}, draft_id=draft['id'])
        submit_draft(store, 'maintainer', draft['id'])
        item = review_draft(store, 'reviewer', draft['id'], True)
        assert item['version'] == 1 and item['status'] == 'published', item
        assert len(store.published()) == 1

        # 修订：版本递增，原版本被替换
        revised = create_draft(store, 'maintainer', {**base, 'answer': '修订后的答案'}, target_id=item['id'])
        assert revised['baseVersion'] == 1
        submit_draft(store, 'maintainer', revised['id'])
        item2 = review_draft(store, 'reviewer', revised['id'], True)
        assert item2['id'] == item['id'] and item2['version'] == 2, item2
        assert len(store.published()) == 1, '修订应替换原条目而不是新增'

        # 乐观锁：拿旧版本号再发布要报冲突
        stale = create_draft(store, 'maintainer', {**base, 'answer': '基于旧版本'}, target_id=item['id'])
        submit_draft(store, 'maintainer', stale['id'])
        store.drafts()[0]['baseVersion'] = 1
        store.save_drafts(store.drafts())
        try:
            review_draft(store, 'reviewer', stale['id'], True)
            raise AssertionError('版本冲突应被拦截')
        except ValueError as e:
            assert '版本' in str(e)

        # 审计留痕（FR-34）
        actions = [rec['action'] for rec in store.log(50)]
        for expected in ('新建草稿', '提交审核', '驳回知识'):
            assert expected in actions, '审计缺少动作：%s' % expected
        assert any(a.startswith('审核发布') for a in actions)
        assert all(rec['actor'] and rec['time'] and rec['target'] for rec in store.log(50))
        print('PASS 字段校验、角色越权、已提交版本冻结、作者自审阻断、驳回需原因、版本递增、乐观锁、审计留痕')
        print('管理端自测通过（纯内存运行，未改动 knowledge_base/data/）')
        return 0


# ---------------------------------------------------------------- 命令行

def build_parser():
    ap = argparse.ArgumentParser(description='知识维护与审核（管理端）')
    ap.add_argument('--data', default=DATA, help='数据目录，默认 knowledge_base/data')
    sub = ap.add_subparsers(dest='cmd')

    d = sub.add_parser('draft', help='新建或修改草稿（知识维护人员）')
    d.add_argument('--actor', required=True)
    d.add_argument('--id', default='', help='要修改的草稿 ID')
    d.add_argument('--target', default='', help='要修订的已发布知识 ID')
    d.add_argument('--kb', dest='kbId', required=True, help='知识库 ID：%s' % ' / '.join(library_ids()))
    d.add_argument('--title', required=True)
    d.add_argument('--category', required=True)
    d.add_argument('--answer', required=True)
    d.add_argument('--source', required=True)
    d.add_argument('--channel', required=True)
    d.add_argument('--scope', required=True)
    d.add_argument('--aliases', default='')
    d.add_argument('--steps', default='')
    d.add_argument('--article', default='')
    d.add_argument('--page', default='0')
    d.add_argument('--effective-from', dest='effectiveFrom', default='')
    d.add_argument('--effective-to', dest='effectiveTo', default='')
    d.add_argument('--long-term', dest='longTerm', action='store_true')

    s = sub.add_parser('submit', help='提交审核（知识维护人员）')
    s.add_argument('--actor', required=True)
    s.add_argument('--id', required=True)

    r = sub.add_parser('review', help='审核发布或驳回（知识审核员）')
    r.add_argument('--actor', required=True)
    r.add_argument('--id', required=True)
    r.add_argument('--approve', action='store_true')
    r.add_argument('--reject', action='store_true')
    r.add_argument('--reason', default='')

    l = sub.add_parser('list', help='列出草稿或已发布知识')
    l.add_argument('--status', default='')
    l.add_argument('--published', action='store_true')

    g = sub.add_parser('log', help='查看审计日志')
    g.add_argument('--limit', type=int, default=20)

    sub.add_parser('selftest', help='跑一遍全部规则，不需要任何外部依赖')
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.cmd == 'selftest':
        return selftest()
    if not args.cmd:
        build_parser().print_help()
        return 1

    store = Store(args.data)
    try:
        if args.cmd == 'draft':
            draft = create_draft(store, args.actor, vars(args), draft_id=args.id, target_id=args.target)
            print('草稿 %s（%s）已保存' % (draft['id'], draft['status']))
        elif args.cmd == 'submit':
            draft = submit_draft(store, args.actor, args.id)
            print('草稿 %s 已提交审核，等待审核员处理' % draft['id'])
        elif args.cmd == 'review':
            if args.approve == args.reject:
                raise ValueError('请二选一：--approve 或 --reject')
            if args.approve:
                item = review_draft(store, args.actor, args.id, True)
                print('已发布 %s v%d（知识库 %s）' % (item['id'], item['version'], item['kbId']))
            else:
                draft = review_draft(store, args.actor, args.id, False, args.reason)
                print('已驳回 %s：%s' % (draft['id'], draft['reason']))
        elif args.cmd == 'list':
            if args.published:
                for item in store.published():
                    print('%-14s v%-3d %-12s %s' % (item['id'], item['version'], item['kbId'], item['title']))
            else:
                for draft in store.drafts():
                    if args.status and draft['status'] != args.status:
                        continue
                    print('%-22s %-10s %-12s %s' % (draft['id'], draft['status'], draft['kbId'], draft['title']))
        elif args.cmd == 'log':
            for rec in store.log(args.limit):
                print('%s %-10s %-14s %-22s %s' % (rec['time'], rec['actor'], rec['action'], rec['target'], rec['reason']))
    except (ValueError, PermissionError) as e:
        print('未完成：%s' % e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
