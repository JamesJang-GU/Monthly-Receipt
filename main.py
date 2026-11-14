import json
import os
import calendar
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

# ============ 0. 날짜 ============
now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
month = int(os.environ["FORCE_MONTH"]) if os.environ.get("FORCE_MONTH") else now.month
year = int(os.environ.get("FORCE_YEAR", now.year))

last_day = calendar.monthrange(year, month)[1]
due_date = f"{year}.{month:02d}.{last_day:02d}"      # 명세서 이미지용 납기일
page_date = f"{year}-{month:02d}-14"                  # 👈 노션 페이지 Dutation = 매월 14일
BILL_TITLE = f"[KT] {month}월 명세서"                 # 이미지 상단 문구
PAGE_TITLE = "전표처리_휴대전화요금(14일)"             # 👈 노션 페이지 제목 (고정)

# ============ 1. 명세서 값 ============
DEFAULTS = {
    "amount": "76,140",
    "service_no": "010-26**-*658",
    "customer": "장정*",
    "bill_no": "92029089459",
    "installment": "76,147",
    "discount": "-7",
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

# ============ 2. 이미지 렌더링 ============
W = 1080
MARGIN_X, MARGIN_Y = 72, 90
FONT_SIZE = 40
LINE_H, BLANK_H = 66, 46
BG, FG = (18, 18, 20), (232, 232, 234)

FD = Path("assets/fonts")
if not (FD / "NanumGothic.ttf").exists():
    raise SystemExit("❌ 한글 폰트 없음 → 워크플로우의 폰트 다운로드 단계를 확인하세요")
f_reg = ImageFont.truetype(str(FD / "NanumGothic.ttf"), FONT_SIZE)
f_bold = ImageFont.truetype(str(FD / "NanumGothic-Bold.ttf"), FONT_SIZE)

content = [
    [("[Web발신]", "r")],
    [(BILL_TITLE, "r")],
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
    [("납기일 : ", "r"), (due_date, "bu")],
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
        if "u" in style:
            ascent, _ = font.getmetrics()
            uy = y + ascent + 6
            d.line([(x, uy), (x + w, uy)], fill=FG, width=3)
        x += w
    y += LINE_H

out = Path(f"out/{year}-{month:02d}-kt-bill.png")
out.parent.mkdir(exist_ok=True)
img.save(out, optimize=True)
print(f"✅ {out} ({W}x{H}) / 납기일 {due_date}")

# ============ 3. Notion 업로드 ============
# ① 업로드 객체
r = requests.post(f"{API}/file_uploads", headers=json_headers,
                  json={"filename": out.name, "content_type": "image/png"})
r.raise_for_status()
upload_id = r.json()["id"]

# ② 파일 전송
send_headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": VERSION}
with out.open("rb") as f:
    s = requests.post(f"{API}/file_uploads/{upload_id}/send",
                      headers=send_headers,
                      files={"file": (out.name, f, "image/png")})
    s.raise_for_status()

# ③ 페이지 생성 — 스크린샷의 속성 그대로
TITLE_PROP = os.environ.get("NOTION_TITLE_PROP", "이름")   # 👈 DB의 Title 속성명 (다르면 Secret으로 덮어쓰기)

properties = {
    TITLE_PROP:  {"title": [{"text": {"content": PAGE_TITLE}}]},
    "Dutation":  {"date": {"start": page_date}},           # 매월 14일
    "카테고리":  {"select": {"name": "사내/행정"}},
    "상태":      {"status": {"name": "시작 전"}},
    "우선순위":  {"select": {"name": "상"}},
}

payload = {
    "parent": {"database_id": DATABASE_ID},
    "properties": properties,
    "children": [{
        "object": "block",
        "type": "image",
        "image": {
            "type": "file_upload",
            "file_upload": {"id": upload_id},
            "caption": [{"type": "text",
                         "text": {"content": f"{year}년 {month}월 / 납기일 {due_date}"}}],
        },
    }],
}
p = requests.post(f"{API}/pages", headers=json_headers, json=payload)
if p.status_code >= 400:
    print("❌ Notion 응답:", p.status_code, p.text)
p.raise_for_status()
print(f"🚀 Notion → {p.json()['url']}")
