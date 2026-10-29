# -*- coding: utf-8 -*-
"""在 pip 无法正常工作的沙箱里，直接从镜像下载 wheel 并解压到 venv。

只用于本机环境准备，不属于检索层代码，装完即可删除。
"""
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from urllib.parse import urljoin

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(WS, '.venv', 'Lib', 'site-packages')
WHEEL_DIR = os.path.join(WS, '.tmp', 'wheels')
INDEX = 'https://pypi.tuna.tsinghua.edu.cn/simple/%s/'

TARGETS = [
    ('transformers', r'transformers-4\.56\.2-py3-none-any\.whl'),
    ('tokenizers', r'tokenizers-0\.22\.2-cp3\d+-abi3-win_amd64\.whl'),
    ('regex', r'regex-2025\.9\.18-cp311-cp311-win_amd64\.whl'),
    ('huggingface-hub', r'huggingface_hub-0\.3[4-9]\.\d+-py3-none-any\.whl'),
]


def find_wheel(pkg, pattern):
    base = INDEX % pkg
    html = urllib.request.urlopen(base, timeout=30).read().decode('utf-8', 'ignore')
    links = re.findall(r'href="([^"]+)"', html)
    for link in links:
        name = link.split('#')[0].split('/')[-1]
        if re.search(pattern, name):
            return urljoin(base, link)
    raise SystemExit('%s 未找到匹配 wheel，候选 %d 个' % (pkg, len(links)))


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return dest
    tmp = dest + '.part'
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, 'wb') as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)
    return dest


def clean_old(pkg):
    """删掉旧版本目录与 dist-info，避免 5.x 与 4.x 混在一起。"""
    for name in os.listdir(SITE):
        low = name.lower()
        if low in (pkg, pkg.replace('-', '_')) or low.startswith(pkg.replace('-', '_') + '-'):
            path = os.path.join(SITE, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                print('  删除旧目录', name)


def install(wheel):
    with zipfile.ZipFile(wheel) as z:
        z.extractall(SITE)
        return [n for n in z.namelist() if n.endswith('dist-info/METADATA')][:1]


def main():
    os.makedirs(WHEEL_DIR, exist_ok=True)
    for pkg, pattern in TARGETS:
        url = find_wheel(pkg, pattern)
        name = url.split('/')[-1]
        print('%s → %s' % (pkg, name))
        path = download(url, os.path.join(WHEEL_DIR, name))
        clean_old(pkg)
        install(path)
        print('  已解压到 %s (%.1f MB)' % (SITE, os.path.getsize(path) / 2 ** 20))
    print('\n完成，请验证 import。')
    return 0


if __name__ == '__main__':
    sys.exit(main())


