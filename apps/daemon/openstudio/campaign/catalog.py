"""Danh mục thị trường & nền tảng + bản địa hoá xác định (giá, múi giờ, lịch đăng).

Các mục "gợi ý văn hoá" là hướng dẫn chung để LLM viết đúng giọng; KHÔNG thay cho người bản ngữ rà soát.
Giới hạn ký tự của TikTok/Facebook là mức khuyến nghị an toàn do OpenStudio đặt, không phải số liệu chính thức của nền tảng."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MARKETS: dict[str, dict] = {
    "us": {"name": "Hoa Kỳ", "lang": "en", "region": "en-US", "currency": "USD", "tz": "America/New_York", "units": "imperial", "date": "MM/DD/YYYY",
           "formality": "casual", "address": "dùng 'you', thân thiện, trực tiếp",
           "notes": ["Giá thường chưa gồm thuế bán hàng; ghi rõ nếu cần.", "Dùng đơn vị Anh-Mỹ (miles, °F, lb, oz, ft) khi có số đo.", "CTA ngắn, rõ; tránh thành ngữ khó dịch."]},
    "uk": {"name": "Anh", "lang": "en", "region": "en-GB", "currency": "GBP", "tz": "Europe/London", "units": "metric", "date": "DD/MM/YYYY",
           "formality": "casual", "address": "dùng 'you', giọng lịch sự, ít khoa trương",
           "notes": ["Dùng chính tả Anh (colour, organise).", "Ngày theo DD/MM/YYYY.", "Khoảng cách trên đường có thể dùng dặm (miles)."]},
    "jp": {"name": "Nhật Bản", "lang": "ja", "region": "ja-JP", "currency": "JPY", "tz": "Asia/Tokyo", "units": "metric", "date": "YYYY年M月D日",
           "formality": "formal", "address": "dùng thể lịch sự です/ます; tránh gọi 'あなた' lặp lại",
           "notes": ["Giá thường ghi kèm thuế (税込) — chỉ ghi nếu brief nói rõ.", "Tránh lời khoa trương quá mức; ưu tiên giọng lịch sự, tôn trọng.", "Ngày theo YYYY年M月D日."]},
    "kr": {"name": "Hàn Quốc", "lang": "ko", "region": "ko-KR", "currency": "KRW", "tz": "Asia/Seoul", "units": "metric", "date": "YYYY.MM.DD",
           "formality": "formal", "address": "dùng đuôi lịch sự (해요체/합쇼체)",
           "notes": ["Số tiền lớn có thể dùng '만 원'.", "Ngày theo YYYY.MM.DD.", "Giọng thân thiện nhưng vẫn lịch sự."]},
    "cn": {"name": "Trung Quốc đại lục", "lang": "zh", "region": "zh-CN", "currency": "CNY", "tz": "Asia/Shanghai", "units": "metric", "date": "YYYY年M月D日",
           "formality": "neutral", "address": "dùng chữ giản thể; xưng 您 khi cần trang trọng",
           "notes": ["Dùng chữ Hán giản thể.", "TikTok, Facebook và YouTube không truy cập được ở Trung Quốc đại lục; thị trường này thường dùng Douyin/WeChat/Bilibili (OpenStudio chưa hỗ trợ)."],
           "blocked_platforms": ["youtube", "tiktok", "facebook"]},
    "vn": {"name": "Việt Nam", "lang": "vi", "region": "vi-VN", "currency": "VND", "tz": "Asia/Ho_Chi_Minh", "units": "metric", "date": "DD/MM/YYYY",
           "formality": "casual", "address": "xưng 'mình' – gọi 'bạn' (hoặc 'anh/chị' nếu trang trọng)",
           "notes": ["Giá ghi dạng 299.000đ.", "Ngày theo DD/MM/YYYY.", "Giọng gần gũi; tránh dịch word-by-word từ tiếng Anh."]},
    "fr": {"name": "Pháp", "lang": "fr", "region": "fr-FR", "currency": "EUR", "tz": "Europe/Paris", "units": "metric", "date": "DD/MM/YYYY",
           "formality": "neutral", "address": "'vous' cho quảng cáo chung, 'tu' nếu thương hiệu trẻ/thân mật",
           "notes": ["Giá ghi dạng 11,99 € (dấu phẩy thập phân).", "Giá thường đã gồm thuế (TTC)."]},
    "de": {"name": "Đức", "lang": "de", "region": "de-DE", "currency": "EUR", "tz": "Europe/Berlin", "units": "metric", "date": "DD.MM.YYYY",
           "formality": "formal", "address": "'Sie' cho quảng cáo chung, 'du' nếu thương hiệu trẻ",
           "notes": ["Giá ghi dạng 11,99 € và thường đã gồm MwSt.", "Ngày theo DD.MM.YYYY.", "Thông tin cần chính xác, ít phóng đại."]},
    "es": {"name": "Tây Ban Nha", "lang": "es", "region": "es-ES", "currency": "EUR", "tz": "Europe/Madrid", "units": "metric", "date": "DD/MM/YYYY",
           "formality": "casual", "address": "'tú' cho giọng thân thiện, 'usted' nếu trang trọng",
           "notes": ["Giá ghi dạng 11,99 €.", "Tây Ban Nha khác Mỹ Latinh về từ vựng và cách xưng hô."]},
    "br": {"name": "Brazil", "lang": "pt", "region": "pt-BR", "currency": "BRL", "tz": "America/Sao_Paulo", "units": "metric", "date": "DD/MM/YYYY",
           "formality": "casual", "address": "'você', giọng ấm áp",
           "notes": ["Giá ghi dạng R$ 59,90.", "Dùng tiếng Bồ Đào Nha-Brazil, không phải Bồ Đào Nha châu Âu."]},
    "th": {"name": "Thái Lan", "lang": "th", "region": "th-TH", "currency": "THB", "tz": "Asia/Bangkok", "units": "metric", "date": "DD/MM/YYYY",
           "formality": "formal", "address": "dùng tiểu từ lịch sự ค่ะ/ครับ",
           "notes": ["Giá ghi dạng ฿390.", "Năm Phật lịch (พ.ศ.) xuất hiện trong văn bản chính thức."]},
    "id": {"name": "Indonesia", "lang": "id", "region": "id-ID", "currency": "IDR", "tz": "Asia/Jakarta", "units": "metric", "date": "DD/MM/YYYY",
           "formality": "casual", "address": "'kamu' thân mật hoặc 'Anda' trang trọng",
           "notes": ["Giá ghi dạng Rp 190.000.", "Chú ý quy ước halal/nhạy cảm tôn giáo với nội dung thực phẩm."]},
}

PLATFORMS: dict[str, dict] = {
    "youtube": {"name": "YouTube", "per_week": 2, "offset": 1, "time": "18:00", "title_limit": 100, "caption_limit": 600, "hashtags": 5,
                "formats": ["long_video", "short_video"], "aspect": {"long_video": "16:9", "short_video": "9:16"}},
    "tiktok": {"name": "TikTok", "per_week": 3, "offset": 0, "time": "19:00", "title_limit": 80, "caption_limit": 300, "hashtags": 5,
               "formats": ["short_video"], "aspect": {"short_video": "9:16"}},
    "facebook": {"name": "Facebook", "per_week": 2, "offset": 2, "time": "12:00", "title_limit": 100, "caption_limit": 500, "hashtags": 3,
                 "formats": ["short_video", "post"], "aspect": {"short_video": "9:16", "post": "1:1"}},
}
PLATFORM_ORDER = list(PLATFORMS)


def market_warnings(markets: list[str], platforms: list[str]) -> list[str]:
    out = []
    for m in markets:
        blocked = [p for p in platforms if p in MARKETS[m].get("blocked_platforms", [])]
        if blocked:
            out.append(f"{MARKETS[m]['name']}: {', '.join(PLATFORMS[p]['name'] for p in blocked)} không dùng được ở thị trường này — nên bỏ hoặc thay bằng nền tảng bản địa.")
    return out


# ---------- tiền tệ (xác định, không để LLM tự quy đổi) ----------
def _group(n: int, sep: str) -> str:
    return f"{n:,}".replace(",", sep)


def format_money(amount: float, currency: str) -> str:
    c = currency.upper()
    if c == "USD":
        return f"${amount:,.2f}"
    if c == "GBP":
        return f"£{amount:,.2f}"
    if c == "EUR":
        whole, frac = f"{amount:,.2f}".split(".")
        return f"{whole.replace(',', '.')},{frac} €"
    if c == "JPY":
        return f"¥{round(amount):,}"
    if c == "CNY":
        return f"¥{amount:,.0f}" if float(amount).is_integer() else f"¥{amount:,.2f}"
    if c == "KRW":
        return f"₩{round(amount):,}"
    if c == "VND":
        return f"{_group(round(amount), '.')}đ"
    if c == "BRL":
        whole, frac = f"{amount:,.2f}".split(".")
        return f"R$ {whole.replace(',', '.')},{frac}"
    if c == "THB":
        return f"฿{round(amount):,}"
    if c == "IDR":
        return f"Rp {_group(round(amount), '.')}"
    return f"{amount:,.2f} {c}"


def local_price(price_vnd: float | None, fx: dict[str, float], currency: str) -> str | None:
    """Giá địa phương = giá VND / tỷ giá do NGƯỜI DÙNG nhập (VND cho 1 đơn vị tiền tệ). Không có tỷ giá → None (không bịa)."""
    if price_vnd is None:
        return None
    if currency == "VND":
        return format_money(price_vnd, "VND")
    rate = fx.get(currency)
    if not rate or rate <= 0:
        return None
    return format_money(price_vnd / rate, currency)


# ---------- lịch ----------
def build_schedule(n_ideas_per_market: dict[str, int], markets: list[str], platforms: list[str], days: int, start: date,
                   per_week: dict[str, int] | None = None) -> list[dict]:
    """Lịch đăng xác định: mỗi (thị trường, nền tảng) đăng `per_week` bài/tuần, rải đều, lệch ngày theo nền tảng để không dồn một ngày.
    Mỗi thị trường dùng CÙNG chuỗi ý tưởng (đánh số theo thứ tự đăng) → chiến dịch nhất quán giữa các nước."""
    per_week = {**{p: PLATFORMS[p]["per_week"] for p in platforms}, **(per_week or {})}
    posts: list[dict] = []
    for m in markets:
        mine: list[dict] = []
        for p in platforms:
            n = max(1, per_week[p])
            slots = sorted({round(i * 7 / n) % 7 for i in range(n)})
            for d in range(days):
                if (d - PLATFORMS[p]["offset"]) % 7 in slots and d >= 0:
                    mine.append({"day": d + 1, "date": (start + timedelta(days=d)).isoformat(), "time": PLATFORMS[p]["time"], "market": m, "platform": p})
        mine.sort(key=lambda x: (x["day"], PLATFORM_ORDER.index(x["platform"])))
        count: dict[str, int] = {}
        for i, post in enumerate(mine):
            p = post["platform"]
            k = count.get(p, 0)
            count[p] = k + 1
            fmts = PLATFORMS[p]["formats"]
            post["format"] = fmts[0] if len(fmts) == 1 else (fmts[0] if k % 3 == 0 else fmts[1])   # youtube: 1 dài rồi 2 Shorts; facebook: reel nhiều hơn bài chữ
            if p == "facebook":
                post["format"] = "short_video" if k % 2 == 0 else "post"
            post["idea_index"] = i % max(1, n_ideas_per_market.get(m, len(mine)))
        posts.extend(mine)
    for i, post in enumerate(sorted(posts, key=lambda x: (x["date"], x["market"], PLATFORM_ORDER.index(x["platform"]))), 1):
        post["id"] = f"p{i:03d}"
    return sorted(posts, key=lambda x: x["id"])


def ideas_needed(markets: list[str], platforms: list[str], days: int, per_week: dict[str, int] | None = None) -> int:
    start = date(2026, 1, 5)
    sched = build_schedule({}, markets[:1], platforms, days, start, per_week)
    return max(1, len(sched))


def to_utc(date_s: str, time_s: str, tz: str) -> str:
    try:
        z = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        z = timezone.utc
    d = datetime.combine(date.fromisoformat(date_s), time.fromisoformat(time_s), tzinfo=z)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
