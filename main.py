import json
import os
import calendar
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

# ============ 0. 날짜: 매월 13일 실행 → 해당 월 + 그 달의 마지막 날 ============
now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
month = int(os.environ["FORCE_MONTH"]) if os.environ.get("FORCE_MONTH") else now.month
year = int(os.environ.get("FORCE_YEAR", now.year))

last_day = calendar.monthrange(year, month)[1]        # 👈 마지막 날 (윤년 자동)
due_date = f"{year}.{month:02d}.{last_day:02d}"       # 예: 2026.10.31 / 2025.02.28
TITLE = f"[KT] {month}월 명세서"                      # 예: [KT] 10월 명세서

# ============ 1. 명세서 고정 값 (Secret BILL_CONFIG로 덮어쓰기 가능) ============
DEFAULTS = {
    "amount": "76,140",                # 납부/이용 금액
    "service_no": "010-26**-*658",
    "customer": "장정*",
    "bill_no": "92029089459",
    "installment": "76,147",           # 단말기 분할상환금
    "discount": "-7",                  # 할인받으신금액
    "card_owner": "장정*",
    "card_name": "신한카드",
    "card_no": "542879*********8",
    "optout_url": (
        "https://wsgadd.kt.com/bill/s_MmsRcvRfslSetup.do\n"
        "?b=DHZ4thFEl3SuPiEqEvabGg%3D%3D%0D%0A\n"
        "&amp;c=Jd3co1ZWjhszBBIEjZua3w%3D%3D%0D\n"
        "%0A"
    ),
}
secret_cfg = os.environ.get("BILL_CONFIG", "").strip()
CFG = DEFAULTS | (json.loads(secret_cfg) if secret_cfg else {})

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
json_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": VERSION,
    "Content-Type": "application/json",
}

# ============ 2. 이미지 렌더링 (스크린샷과 동일한 다크 포맷) ============
W = 1080
MARGIN_X, MARGIN_Y = 72, 90
FONT_SIZE = 40
LINE_H, BLANK_H = 66, 46
BG, FG = (18, 18, 20), (232, 232, 234)     # 거의 검정 / 밝은 회색

FD = Path("assets/fonts")
if not (FD / "NanumGothic.ttf").exists():
    raise SystemExit("❌ 한글 폰트 없음 → 워크플로우의 폰트 다운로드 단계를 확인하세요")
f_reg = ImageFont.truetype(str(FD / "NanumGothic.ttf"), FONT_SIZE)
f_bold = ImageFont.truetype(str(FD / "NanumGothic-Bold.ttf"), FONT_SIZE)

# style: r=일반, bu=굵게+밑줄, u=밑줄   ← 스크린샷의 강조 위치 그대로
content = [
    [("[Web발신]", "r")],
    [(f"[KT] {month}월 명세서", "r")],                      # 👈 월 자동
    None,
    [(f"납부하실 금액 : {CFG['amount']} 원", "r")],
    [("이용기간 : ~", "r")],
    [(f"서비스번호 : {CFG['service_no']}", "r")],
    [(f"고객명 : {CFG['customer']}", "r")],
    [("명세서번호 : ", "r"), (CFG["bill_no"], "bu")],
    [(f"이용하신 금액 : {CFG['amount']} 원", "r")],
    [("미납요금 : 0 원", "r")],
    None,
    [("[이용하신 내역]", "r")],
    [(f"단말기 분할상환금 : {CFG['installment']} 원", "r")],
    [(f"할인받으신금액 : {CFG['discount']} 원", "r")],
    None,
    [("[납부정보]", "r")],
    [("납기일 : ", "r"), (due_date, "bu")],                 # 👈 그 달의 마지막 날
    [(f"카드주 : {CFG['card_owner']}", "r")],
    [(f"카드명 : {CFG['card_name']}", "r")],
    [(f"카드번호 : {CFG['card_no']}", "r")],
    None,
    [("[고객센터(유료)]", "r")],
    [("유선 100 / 무선 ", "r"), ("1588-0010", "bu")],
    None,
    [("[타인명세서 수신거부 신청]", "r")],
    *[[(u, "u")] for u in CFG["optout_url"].splitlines() if u.strip()],
]

H = MARGIN_Y * 2 + sum(BLANK_H if c is None else LINE_H for c in content)
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

y = MARGIN_Y
for line in content:
    if line is None:
        y += BLANK_H
        continue
    x = MARGIN_X
    for text, style in line:
        font = f_bold if "b" in style else f_reg
        d.text((x, y), text, font=font, fill=FG)
        w = d.textlength(text, font=font)
        if "u" in style:                                  # 밑줄 직접 그리기
            ascent, _ = font.getmetrics()
            uy = y + ascent + 6
            d.line([(x, uy), (x + w, uy)], fill=FG, width=3)
        x += w
    y += LINE_H

out = Path(f"out/{year}-{month:02d}-kt-bill.png")
out.parent.mkdir(exist_ok=True)
img.save(out, optimize=True)
print(f"✅ {out} ({W}x{H}) / 납기일 {due_date}")

# ============ 3. Notion 업로드 (공식 3단계, 이전과 동일) ============
r = requests.post(f"{API}/file_uploads", headers=json_headers,
                  json={"filename": out.name, "content_type": "image/png"})
r.raise_for_status()
upload_id = r.json()["id"]

send_headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": VERSION}
with out.open("rb") as f:          # ⚠️ Content-Type 수동 지정 금지
    s = requests.post(f"{API}/file_uploads/{upload_id}/send",
                      headers=send_headers,
                      files={"file": (out.name, f, "image/png")})
    s.raise_for_status()

payload = {
    "parent": {"database_id": DATABASE_ID},
    "properties": {
        "Name": {"title": [{"text": {"content": TITLE}}]},
        "Month": {"number": month},
        "Date": {"date": {"start": now.date().isoformat()}},
    },
    "children": [{
        "object": "block",
        "type": "image",
        "image": {
            "type": "file_upload",
            "file_upload": {"id": upload_id},
            "caption": [{"type": "text",
                         "text": {"content": f"{year}-{month:02d} / 납기일 {due_date}"}}],
        },
    }],
}
p = requests.post(f"{API}/pages", headers=json_headers, json=payload)
p.raise_for_status()
print(f"🚀 Notion → {p.json()['url']}")
