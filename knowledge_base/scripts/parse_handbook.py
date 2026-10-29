# -*- coding: utf-8 -*-
"""从《杭州电子科技大学学生手册》PDF 生成可入库的知识库语料。

零第三方依赖：只使用 Python 标准库自行解析 PDF 的文本层（ToUnicode CMap + Identity-H），
因为该 PDF 的文本层是按字形片段（BT/ET 块）排布的，需要按坐标重排才能得到正确语序。

用法：
    python parse_handbook.py --pdf "C:\\path\\to\\学生手册.pdf" --out ..\\data

产出：
    handbook_pages.json   按页的清洗后文本
    handbook_fulltext.txt 带页码标记的全文（人工校对用）
    handbook_docs.json    文档清单（名称、起止页、章节数、条数）
    handbook_chunks.jsonl RAG 切块（文档/章/节/条/页码/正文）
"""
import argparse
import hashlib
import json
import os
import re
import zlib

# ---------------------------------------------------------------- PDF 文本提取

OBJ_RE = re.compile(rb'(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj', re.S)
TJ_RE = re.compile(rb'\[(.*?)\]\s*TJ', re.S)
CM_RE = re.compile(rb'(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+cm')
TF_RE = re.compile(rb'/([A-Za-z0-9]+)\s+([\d.]+)\s+Tf')


class Pdf:
    def __init__(self, path):
        self.raw = open(path, 'rb').read()
        self.objs = {int(m.group(1)): m.group(3) for m in OBJ_RE.finditer(self.raw)}
        self._cmaps = {}

    def stream(self, num):
        body = self.objs.get(num)
        if body is None:
            return None
        i = body.find(b'stream')
        if i < 0:
            return None
        j = i + 6
        if body[j:j + 2] == b'\r\n':
            j += 2
        elif body[j:j + 1] in (b'\n', b'\r'):
            j += 1
        k = body.find(b'endstream', j)
        data = body[j:k]
        if b'FlateDecode' in body[:i]:
            try:
                return zlib.decompressobj().decompress(data)
            except zlib.error:
                return None
        return data

    def cmap(self, font_obj):
        if font_obj in self._cmaps:
            return self._cmaps[font_obj]
        table = {}
        body = self.objs.get(font_obj, b'')
        m = re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R', body)
        if m:
            data = self.stream(int(m.group(1)))
            if data:
                table = parse_cmap(data)
        self._cmaps[font_obj] = table
        return table

    def page_numbers(self):
        return sorted(n for n, b in self.objs.items()
                      if re.search(rb'/Type\s*/Page\b', b))

    def page_fonts(self, body):
        fonts = {}
        m = re.search(rb'/Font\s*<<(.*?)>>', body, re.S)
        if m:
            for name, num in re.findall(rb'/([A-Za-z0-9]+)\s+(\d+)\s+0\s+R', m.group(1)):
                fonts[name.decode()] = int(num)
            return fonts
        m = re.search(rb'/Font\s+(\d+)\s+0\s+R', body)
        if m:
            sub = self.objs.get(int(m.group(1)), b'')
            for name, num in re.findall(rb'/([A-Za-z0-9]+)\s+(\d+)\s+0\s+R', sub):
                fonts[name.decode()] = int(num)
        return fonts

    def page_lines(self, page_obj):
        body = self.objs[page_obj]
        fonts = self.page_fonts(body)
        ids = []
        m = re.search(rb'/Contents\s+(\d+)\s+0\s+R', body)
        if m:
            ids = [int(m.group(1))]
        else:
            m = re.search(rb'/Contents\s*\[(.*?)\]', body, re.S)
            if m:
                ids = [int(v) for v in re.findall(rb'(\d+)\s+0\s+R', m.group(1))]
        content = b''
        for cid in ids:
            s = self.stream(cid)
            if s:
                content += s + b'\n'
        if not content:
            return []
        frags = []
        for blk in re.findall(rb'BT(.*?)ET', content, re.S):
            text, x, y, size = block_text(blk, fonts, self)
            if text.strip():
                frags.append({'y': y, 'x': x, 'size': size, 'text': text})
        return assemble_lines(frags)


def parse_cmap(data):
    table = {}
    for blk in re.findall(rb'beginbfchar(.*?)endbfchar', data, re.S):
        for src, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            try:
                table[int(src, 16)] = bytes.fromhex(dst.decode()).decode('utf-16-be', 'ignore')
            except ValueError:
                pass
    for blk in re.findall(rb'beginbfrange(.*?)endbfrange', data, re.S):
        for lo, hi, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            try:
                a, b = int(lo, 16), int(hi, 16)
                base = bytes.fromhex(dst.decode())
                start = int.from_bytes(base, 'big')
                for k in range(a, min(b, a + 65535) + 1):
                    table[k] = (start + k - a).to_bytes(len(base), 'big').decode('utf-16-be', 'ignore')
            except (ValueError, OverflowError):
                pass
        for lo, hi, arr in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]', blk, re.S):
            try:
                a = int(lo, 16)
                for idx, item in enumerate(re.findall(rb'<([0-9A-Fa-f]+)>', arr)):
                    table[a + idx] = bytes.fromhex(item.decode()).decode('utf-16-be', 'ignore')
            except ValueError:
                pass
    return table


def unescape_literal(s):
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == 0x5c and i + 1 < len(s):
            n = s[i + 1]
            mapping = {0x6e: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
            if n in mapping:
                out.append(mapping[n])
                i += 2
                continue
            if 0x30 <= n <= 0x37:
                digs = s[i + 1:i + 4]
                k = 0
                while k < 3 and k < len(digs) and 0x30 <= digs[k] <= 0x37:
                    k += 1
                out.append(int(digs[:k], 8) & 0xFF)
                i += 1 + k
                continue
            out.append(n)
            i += 2
            continue
        out.append(c)
        i += 1
    return bytes(out)


def decode_hex(hexes, cmap):
    hx = re.sub(rb'\s', b'', hexes)
    if len(hx) % 2:
        hx += b'0'
    try:
        bs = bytes.fromhex(hx.decode())
    except ValueError:
        return ''
    if cmap:
        if len(bs) % 2:
            return ''
        return ''.join(cmap.get((bs[i] << 8) | bs[i + 1], '') for i in range(0, len(bs), 2))
    return bs.decode('latin-1', 'ignore')


def block_text(blk, fonts, pdf):
    m = TF_RE.search(blk)
    name = m.group(1).decode() if m else None
    cmap = pdf.cmap(fonts[name]) if name in fonts else {}
    cms = CM_RE.findall(blk)
    x = y = 0.0
    size = 10.0
    if cms:
        a, b, c, d, e, f = (float(v) for v in cms[-1])
        x, y = e, f
        size = abs(a) or abs(d) or 10.0
    parts = []
    for mm in TJ_RE.finditer(blk):
        for tok in re.finditer(rb'<([0-9A-Fa-f\s]*)>|\(((?:\\.|[^\\()])*)\)', mm.group(1)):
            if tok.group(1) is not None:
                parts.append(decode_hex(tok.group(1), cmap))
            else:
                bs = unescape_literal(tok.group(2))
                parts.append(decode_hex(bs.hex().encode(), cmap) if cmap else bs.decode('latin-1', 'ignore'))
    for mm in re.finditer(rb'<([0-9A-Fa-f\s]*)>\s*Tj', blk):
        parts.append(decode_hex(mm.group(1), cmap))
    return ''.join(parts), x, y, size


def run_width(text, size):
    return sum(size * (0.5 if ord(ch) < 128 else 1.0) for ch in text)


def assemble_lines(frags):
    """同一视觉行的片段按 x 排序；y 相差 2pt 内视为同一行（该 PDF 存在 0.1pt 抖动）。"""
    frags.sort(key=lambda f: -f['y'])
    groups = []
    for f in frags:
        if groups and abs(groups[-1][0]['y'] - f['y']) <= 2.2:
            groups[-1].append(f)
        else:
            groups.append([f])
    lines = []
    for group in groups:
        group.sort(key=lambda f: f['x'])
        buf = ''
        prev_end = None
        for f in group:
            if prev_end is not None and f['x'] - prev_end > 0.55 * f['size'] and buf and not buf.endswith(' '):
                buf += ' '
            buf += f['text']
            prev_end = f['x'] + run_width(f['text'], f['size'])
        lines.append(buf.strip())
    return lines


# ---------------------------------------------------------------- 文本清洗

# 该 PDF 的文本层来自 OCR，存在固定的字形替换错误。注意这些替换必须带上下文：
# 「暂」「也」「页」「]」在正文里都是常用字，只有出现在文号「杭电教[2013]146号」
# 的位置上才是括号被认错，全局替换会把「暂缓注册」改成「]缓注册」。
OCR_FIXES = [
    (re.compile('渊'), '（'),
    (re.compile('冤'), '）'),
    (re.compile('尧'), '、'),
    (re.compile('咱'), '['),                 # 文号左括号
    (re.compile(r'(?<=\d)也(?=\d)'), '['),   # 杭电本也2017页180号
    (re.compile(r'(?<=\d)暂(?=\d)'), ']'),   # 杭电教[2013]暂146号
    (re.compile(r'(?<=\d)页(?=\d)'), ']'),   # 杭电本[2017页180号
]
CJK_PUNCT = '，。；：、（）《》【】“”‘’！？—…'
FOOTER_RE = re.compile(r'^[·・]\s*(\d+)\s*[·・]$')


def clean_line(line):
    s = line
    for pattern, repl in OCR_FIXES:
        s = pattern.sub(repl, s)
    # 去掉中文标点两侧被误插的空格
    s = re.sub(r'\s+([%s])' % re.escape(CJK_PUNCT), r'\1', s)
    s = re.sub(r'([%s])\s+' % re.escape(CJK_PUNCT), r'\1', s)
    # 章/节 标题后补空格：第九章学业警示与退学
    s = re.sub(r'^(第[一二三四五六七八九十百]+[章节])(?=\S)', r'\1 ', s)
    s = re.sub(r'[ \t]{2,}', ' ', s)
    return s.strip()


def clean_page(lines):
    out, footer = [], ''
    for line in lines:
        line = clean_line(line)
        if not line:
            continue
        m = FOOTER_RE.match(line)
        if m:
            footer = m.group(1)
            continue
        out.append(line)
    return out, footer


# ---------------------------------------------------------------- 结构切分

DOCS = [
    (1, '普通高等学校学生管理规定'),
    (22, '高等学校学生行为准则'),
    (24, '学生伤害事故处理办法'),
    (34, '杭州电子科技大学本科学生学籍管理规定'),
    (56, '杭州电子科技大学本科学生成绩管理规定'),
    (59, '杭州电子科技大学本科学生转学实施细则（试行）'),
    (64, '杭州电子科技大学转专业（类）与大类分流实施办法'),
    (70, '杭州电子科技大学本科毕业生学士学位授予细则'),
    (74, '杭州电子科技大学学生纪律处分实施细则'),
    (88, '杭州电子科技大学学生校内申诉管理规定'),
    (95, '考场规则'),
    (98, '杭州电子科技大学学生考试违规、作弊的认定办法'),
    (101, '杭州电子科技大学本科生选课管理办法'),
    (106, '杭州电子科技大学本科生修读辅修专业、第二本科专业、第二学士学位的管理办法'),
    (112, '杭州电子科技大学本科生课外教育管理规定'),
    (116, '关于学生参加毕业设计（论文）的若干规定'),
    (118, '杭州电子科技大学创新与拓展学分认定管理办法'),
    (127, '课堂管理规则'),
    (129, '杭州电子科技大学学生证、校徽和火车票优惠卡管理办法'),
    (131, '杭州电子科技大学三好学生、优秀学生干部评比办法'),
    (134, '杭州电子科技大学本科生奖学金评审办法'),
    (139, '杭州电子科技大学学生综合测评实施办法'),
    (143, '杭州电子科技大学国家奖学金、省政府奖学金、国家励志奖学金和国家助学金评比办法'),
    (158, '杭州电子科技大学家庭经济困难学生认定办法'),
    (164, '杭州电子科技大学学生校内勤工助学管理办法'),
    (171, '杭州电子科技大学学生住宿管理规定'),
    (180, '杭州电子科技大学学生医疗相关规定'),
    (188, '杭州电子科技大学学生社团管理条例（试行）'),
]
BODY_END = 206
CN_NUM = '一二三四五六七八九十百零〇'
RE_CHAPTER = re.compile(r'^第([%s]+)章\s*(.*)$' % CN_NUM)
RE_SECTION = re.compile(r'^第([%s]+)节\s*(.*)$' % CN_NUM)
RE_ARTICLE = re.compile(r'^第([%s]+)条[\s　]*(.*)$' % CN_NUM)
RE_ARTICLE_GAP = re.compile(r'^第([%s]+)条[\s　]' % CN_NUM)
RE_ENUM = re.compile(r'^([一二三四五六七八九十]+)、\s*(.*)$')
# 表格页（创新学分一览表、奖学金金额表、保险赔付表）保持原样，不参与条目切分
TABLE_PAGES = {123, 124, 125, 126, 136, 137, 186, 187, 197, 198, 199, 200, 201,
               202, 203, 204, 205}


def doc_ranges():
    out = []
    for i, (start, name) in enumerate(DOCS):
        end = DOCS[i + 1][0] - 1 if i + 1 < len(DOCS) else BODY_END
        out.append({'index': i + 1, 'name': name, 'page_start': start, 'page_end': end})
    return out


MIN_CHUNK = 80      # 少于此字数只做复核标记，不跨条合并
MAX_CHUNK = 900     # 超长条不拆分，标记出来供人工复核

RE_PAREN_ITEM = re.compile(r'^（([一二三四五六七八九十]+)）\s*(.*)$')

# 性的正文里会跟着「第二条所列情况」「第三条规定」这类跨行衔接语，
# 它们形似条标题却不是新的一条（这一类在原文中没有条号后的空格）。
ARTICLE_CONNECTORS = ('所列', '所述', '规定', '要求', '中', '之', '所', '的',
                      '和', '与', '及', '或', '内', '外', '、')


def article_head(line):
    m = RE_ARTICLE.match(line)
    if not m:
        return None
    if not RE_ARTICLE_GAP.match(line):
        rest = m.group(2)
        if rest[:2] in ARTICLE_CONNECTORS or rest[:1] in ARTICLE_CONNECTORS:
            return None
    return '第%s条' % m.group(1), m.group(2)


def doc_line_stream(pages, doc):
    """按页序取出该文档的 (page, line)，跳过表格页与页眉页脚。"""
    for pno in range(doc['page_start'], doc['page_end'] + 1):
        if pno in TABLE_PAGES:
            continue
        for line in pages.get(pno, {}).get('lines', []):
            if line and line not in ('杭州电子科技大学', doc['name']):
                yield pno, line


def build_chunks(pages):
    """把每个文档拆成 章/节/条 结构，再按条切块。

    手册里存在两类编排：一类用「第X条」，另一类直接以「一、」「（一）」编号。
    先判断该文档是否含「第X条」，再决定切块边界，避免整篇文档切不出块。
    """
    raw = []
    for doc in doc_ranges():
        lines = list(doc_line_stream(pages, doc))
        has_article = any(RE_ARTICLE.match(t) for _, t in lines)
        has_enum = sum(1 for _, t in lines if RE_ENUM.match(t)) >= 3
        has_paren = sum(1 for _, t in lines if RE_PAREN_ITEM.match(t)) >= 3
        if has_article:
            boundary = 'article'
        elif has_enum:
            boundary = 'enum'
        elif has_paren:
            boundary = 'paren'
        else:
            boundary = 'whole'

        chapter = section = ''
        cur = None
        for pno, line in lines:
            m_ch = RE_CHAPTER.match(line)
            if m_ch:
                chapter, section = '第%s章 %s' % (m_ch.group(1), m_ch.group(2).strip()), ''
                continue
            m_se = RE_SECTION.match(line)
            if m_se:
                section = '第%s节 %s' % (m_se.group(1), m_se.group(2).strip())
                continue

            head = body = None
            m_ar = article_head(line)
            m_en = RE_ENUM.match(line)
            m_pa = RE_PAREN_ITEM.match(line)
            if boundary == 'article' and m_ar:
                head, body = m_ar
            elif boundary == 'enum' and m_en:
                head, body = '%s、' % m_en.group(1), m_en.group(2)
            elif boundary == 'paren' and m_pa:
                head, body = '（%s）' % m_pa.group(1), m_pa.group(2)

            if head:
                if cur:
                    raw.append(cur)
                cur = {'doc': doc['name'], 'doc_index': doc['index'], 'chapter': chapter,
                       'section': section, 'article': head, 'page_start': pno,
                       'page_end': pno, 'lines': [body]}
            elif cur is None:
                # 条之前的文号、制定依据、适用范围等按「导语」保留，不能丢
                cur = {'doc': doc['name'], 'doc_index': doc['index'], 'chapter': chapter,
                       'section': section, 'article': '导语' if boundary != 'whole' else '全文',
                       'page_start': pno, 'page_end': pno, 'lines': [line]}
            else:
                cur['lines'].append(line)
                cur['page_end'] = pno
        if cur:
            raw.append(cur)

    # 不跨条合并：一条即一块。按字数合并会把两条不同主题粘在一起，
    # 破坏「答案必须能指回唯一某条」的引用要求；过短或过长的块只做标记。
    out = []
    for c in raw:
        c['text'] = re.sub(r'\s+', ' ', ''.join(c['lines']).strip())
        c.pop('lines')
        text = c['text']
        if len(text) < 10:
            continue
        label = '《%s》%s' % (c['doc'], c['article'])
        if c['chapter']:
            label += '（%s）' % c['chapter']
        out.append({
            'id': 'hb-%03d' % (len(out) + 1),
            'doc': c['doc'],
            'doc_index': c['doc_index'],
            'chapter': c['chapter'],
            'section': c['section'],
            'article': c['article'],
            'page_start': c['page_start'],
            'page_end': c['page_end'],
            'source': '%s 第%d页' % (label, c['page_start']),
            'text': text,
            'chars': len(text),
            'needs_review': len(text) < MIN_CHUNK or len(text) > MAX_CHUNK,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    pdf = Pdf(args.pdf)
    pages = {}
    for i, obj in enumerate(pdf.page_numbers(), 1):
        lines, footer = clean_page(pdf.page_lines(obj))
        pages[i] = {'page': i, 'footer': footer, 'lines': lines}

    # 第 213 页是重复的散页（页脚为 167），正文只到 206 页
    for pno in [p for p in pages if p > BODY_END]:
        del pages[pno]

    with open(os.path.join(args.out, 'handbook_pages.json'), 'w', encoding='utf-8') as f:
        json.dump([pages[k] for k in sorted(pages)], f, ensure_ascii=False, indent=1)

    fulltext = '\n'.join('<<< 第%d页 >>>\n%s' % (k, '\n'.join(pages[k]['lines']))
                         for k in sorted(pages))
    with open(os.path.join(args.out, 'handbook_fulltext.txt'), 'w', encoding='utf-8') as f:
        f.write(fulltext)

    chunks = build_chunks(pages)
    with open(os.path.join(args.out, 'handbook_chunks.jsonl'), 'w', encoding='utf-8') as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')

    docs = []
    for d in doc_ranges():
        mine = [c for c in chunks if c['doc_index'] == d['index']]
        docs.append(dict(d, chunks=len(mine),
                         chars=sum(c['chars'] for c in mine),
                         chapters=len({c['chapter'] for c in mine if c['chapter']}),
                         articles=len([c for c in mine if c['article'].startswith('第')])))
    with open(os.path.join(args.out, 'handbook_docs.json'), 'w', encoding='utf-8') as f:
        json.dump({'source': os.path.basename(args.pdf), 'pages': len(pages),
                   'chunks': len(chunks), 'chars': sum(c['chars'] for c in chunks),
                   'docs': docs}, f, ensure_ascii=False, indent=1)

    print('pages: %d | chunks: %d | chars: %d | docs: %d' % (
        len(pages), len(chunks), sum(c['chars'] for c in chunks), len(docs)))


if __name__ == '__main__':
    main()
