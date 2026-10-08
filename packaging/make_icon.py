"""產生程式圖示 icon.ico：橘色圓角方塊 + 黑色下載箭頭（與介面左上角的標誌相同）。"""

import os

from PIL import Image, ImageDraw

S = 1024  # 先畫大圖再縮小，邊緣才會平滑
ORANGE = (255, 91, 31, 255)
INK = (10, 10, 10, 255)


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=230, fill=ORANGE)
    w = 92  # 線條粗細

    def line(p, q):
        d.line([p, q], fill=INK, width=w)
        for x, y in (p, q):  # 圓頭
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=INK)

    cx = S / 2
    line((cx, 230), (cx, 640))          # 箭桿
    line((cx, 660), (cx - 190, 470))    # 左翼
    line((cx, 660), (cx + 190, 470))    # 右翼
    line((280, 800), (S - 280, 800))    # 底線
    return img


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    draw().save(out, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
