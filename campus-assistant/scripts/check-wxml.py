# -*- coding: utf-8 -*-
"""WXML 静态检查：标签是否闭合（渲染失败的常见原因）。"""
import os
import re
import sys
import xml.etree.ElementTree as ET

MP = r"D:\校园智能问答系统\AI_chat\campus-assistant\miniprogram"
VOID = {'input', 'image', 'icon', 'progress', 'slider', 'switch', 'textarea', 'canvas', 'import', 'include'}

bad = 0
for root, _, files in os.walk(MP):
    for f in files:
        if not f.endswith('.wxml'):
            continue
        path = os.path.join(root, f)
        src = open(path, encoding='utf-8').read()
        # mustache 里可能含 < > 之外的东西，先抽掉；再把 wx: 前缀改名以通过 XML 解析
        clean = re.sub(r'\{\{.*?\}\}', 'X', src, flags=re.S)
        clean = re.sub(r'\bwx:', 'wx_', clean)
        # wx:else 是布尔属性，XML 要求必须有值，补一个占位值
        clean = re.sub(r'wx_else(?=[\s/>])', 'wx_else="1"', clean)
        clean = re.sub(r'\bwx-for-item\b', 'wx_for_item', clean)
        wrapped = '<root>' + clean + '</root>'
        try:
            ET.fromstring(wrapped)
            print('OK   %s' % os.path.relpath(path, MP))
        except ET.ParseError as e:
            bad += 1
            print('FAIL %s  → %s' % (os.path.relpath(path, MP), e))

print('\n%s' % ('全部 WXML 标签闭合' if not bad else '%d 个文件有标签问题' % bad))
sys.exit(1 if bad else 0)
