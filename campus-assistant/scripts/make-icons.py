# -*- coding: utf-8 -*-
"""生成底部导航的四组图标（灰 / 选中绿各一张，81×81 PNG）。

微信的 tabBar 图标只接受本地 PNG，不能用字体或 SVG。这里用 Pillow 画线条图标，
放大 4 倍绘制再缩小以抗锯齿。改了颜色或形状后重新运行即可：

    python scripts/make-icons.py
"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'miniprogram', 'assets')
SIZE, SCALE = 81, 4
GRAY, GREEN = (147, 160, 155, 255), (23, 107, 91, 255)
W = 5 * SCALE          # 线宽


def canvas():
    image = Image.new('RGBA', (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def p(*values):
    return [v * SCALE for v in values]


def home(d, c):
    d.line(p(13, 40, 40.5, 15, 68, 40), fill=c, width=W, joint='curve')
    d.line(p(21, 35, 21, 66, 60, 66, 60, 35), fill=c, width=W, joint='curve')
    d.line(p(40.5, 66, 40.5, 49), fill=c, width=W)


def chat(d, c):
    d.rounded_rectangle(p(12, 15, 69, 56), radius=10 * SCALE, outline=c, width=W)
    d.line(p(27, 55, 27, 68, 41, 55), fill=c, width=W, joint='curve')
    for x in (29, 40.5, 52):
        d.ellipse(p(x - 3, 32.5, x + 3, 38.5), fill=c)


def book(d, c):
    d.line(p(40.5, 22, 40.5, 66), fill=c, width=W)
    d.line(p(40.5, 22, 28, 16, 12, 16, 12, 60, 28, 60, 40.5, 66), fill=c, width=W, joint='curve')
    d.line(p(40.5, 22, 53, 16, 69, 16, 69, 60, 53, 60, 40.5, 66), fill=c, width=W, joint='curve')


def mine(d, c):
    d.ellipse(p(28, 12, 53, 37), outline=c, width=W)
    d.arc(p(14, 44, 67, 96), start=198, end=342, fill=c, width=W)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, draw in (('home', home), ('chat', chat), ('book', book), ('mine', mine)):
        for suffix, color in (('', GRAY), ('-on', GREEN)):
            image, d = canvas()
            draw(d, color)
            image.resize((SIZE, SIZE), Image.LANCZOS).save(os.path.join(OUT, 'tab-%s%s.png' % (name, suffix)))
    print('已生成 8 张图标 → %s' % OUT)


if __name__ == '__main__':
    main()
