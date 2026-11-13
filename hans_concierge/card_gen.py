import io
import re
import textwrap
from PIL import Image, ImageDraw, ImageFont

# ID Efek Animasi Layar Penuh Resmi Telegram Bot API
EFFECT_CONFETTI = "5046509860389126442"   # 🎉 Konfeti (Beli VIP Pass / Bonus Besar)
EFFECT_FIRE = "5104841245755180586"       # 🔥 Api (Klaim Absen / Misi Harian)
EFFECT_HEART = "5159385139981059251"      # ❤️ Hati (Kirim PM Menfess)
EFFECT_LIKE = "5107584321108051014"       # 👍 Jempol / Apresiasi


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_velvet_frame(draw: ImageDraw.ImageDraw, w: int, h: int, is_vip: bool = False):
    bg_color = (16, 11, 15) if not is_vip else (22, 16, 12)
    draw.rectangle([0, 0, w, h], fill=bg_color)

    for y in range(0, 220):
        alpha = int(35 * (1 - y / 220))
        accent = (110 + alpha, 22, 42) if not is_vip else (140 + alpha, 105, 35)
        draw.line([(0, y), (w, y)], fill=accent)

    gold = (218, 178, 92)
    muted_gold = (130, 104, 52)
    margin = 48
    draw.rectangle([margin, margin, w - margin, h - margin], outline=gold, width=3)
    draw.rectangle([margin + 14, margin + 14, w - margin - 14, h - margin - 14], outline=muted_gold, width=1)


def _build_circular_avatar(avatar_bytes: bytes | None, fallback_name: str, size: int = 156) -> Image.Image:
    """Memotong PP Telegram menjadi lingkaran presisi, atau membuat monogram inisial jika PP disembunyikan."""
    avatar_img = None
    if avatar_bytes:
        try:
            raw = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            # Center crop persegi agar rasio PP tidak gepeng
            min_side = min(raw.width, raw.height)
            left = (raw.width - min_side) // 2
            top = (raw.height - min_side) // 2
            cropped = raw.crop((left, top, left + min_side, top + min_side))
            avatar_img = cropped.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            avatar_img = None

    if avatar_img is None:
        avatar_img = Image.new("RGBA", (size, size), (68, 22, 34, 255))
        d = ImageDraw.Draw(avatar_img)
        clean_chars = [c for c in (fallback_name or "G") if c.isalnum()]
        initial = clean_chars[0].upper() if clean_chars else "V"
        f_init = _load_font(int(size * 0.46), bold=True)
        bbox = d.textbbox((0, 0), initial, font=f_init)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        d.text(((size - tw) / 2, (size - th) / 2 - 6), initial, fill=(224, 186, 102, 255), font=f_init)

    # Masking lingkaran halus
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)

    circular = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circular.paste(avatar_img, (0, 0), mask=mask)
    return circular


def generate_member_card(
    full_name: str,
    username: str,
    coins: int,
    charm: int,
    is_vip: bool,
    vip_until_str: str = "",
    booth_name: str = "",
    ref_code: str = "",
    avatar_bytes: bytes | None = None,
) -> bytes:
    """Kartu Profil & VIP Pass Digital dengan PP Telegram, Nama, & Username (1200 x 720 px)."""
    w, h = 1200, 720
    img = Image.new("RGB", (w, h), (16, 11, 15))
    draw = ImageDraw.Draw(img)
    _draw_velvet_frame(draw, w, h, is_vip=is_vip)

    font_brand = _load_font(25, bold=True)
    font_title = _load_font(42, bold=True)
    font_sub = _load_font(25, bold=False)
    font_stat_label = _load_font(21, bold=False)
    font_stat_val = _load_font(38, bold=True)
    font_footer = _load_font(21, bold=False)

    gold = (224, 186, 102)
    cream = (245, 239, 230)
    silver = (185, 178, 170)

    # Header
    draw.text((92, 86), "THE VELVET HOUR  •  LOUNGE MEMBERSHIP", fill=gold, font=font_brand)
    tier_badge = "VIP RESERVE PASS" if is_vip else "REGULAR GUEST"
    badge_color = (218, 178, 92) if is_vip else (120, 42, 58)
    badge_text_color = (18, 14, 10) if is_vip else cream
    draw.rounded_rectangle([w - 375, 78, w - 88, 128], radius=12, fill=badge_color)
    draw.text((w - 350, 90), tier_badge, fill=badge_text_color, font=_load_font(22, bold=True))

    draw.line([(92, 148), (w - 92, 148)], fill=(95, 78, 44), width=2)

    # Avatar Lingkaran + Bingkai Emas di Kiri
    av_size = 152
    av_x, av_y = 96, 174
    draw.ellipse(
        [av_x - 5, av_y - 5, av_x + av_size + 5, av_y + av_size + 5],
        outline=gold,
        width=3,
    )
    avatar_circle = _build_circular_avatar(avatar_bytes, full_name, size=av_size)
    img.paste(avatar_circle, (av_x, av_y), mask=avatar_circle)

    # Data Nama Telegram & Username di Sebelah Kanan PP
    info_x = av_x + av_size + 34
    clean_name = (full_name or "Guest")[:26]
    draw.text((info_x, 182), clean_name, fill=cream, font=font_title)

    uname_txt = f"@{username}" if username and username != "NoUsername" else "No Public Username"
    draw.text((info_x, 238), uname_txt, fill=silver, font=font_sub)

    if is_vip and vip_until_str:
        extra = f"VIP s/d {vip_until_str}"
        if booth_name:
            extra += f"  •  Booth: {booth_name[:18]}"
        draw.text((info_x, 280), extra, fill=gold, font=_load_font(22, bold=True))
    else:
        draw.text((info_x, 280), "Verified Lounge Member", fill=(160, 148, 136), font=_load_font(22, bold=False))

    # Kotak Statistik (Saldo VC & Charm Points)
    box_y1, box_y2 = 360, 518
    draw.rounded_rectangle([92, box_y1, 575, box_y2], radius=16, fill=(28, 20, 26), outline=(145, 116, 60), width=2)
    draw.text((124, box_y1 + 24), "VELVET COINS BALANCE", fill=silver, font=font_stat_label)
    draw.text((124, box_y1 + 68), f"{coins:,} VC", fill=gold, font=font_stat_val)

    draw.rounded_rectangle([615, box_y1, w - 92, box_y2], radius=16, fill=(28, 20, 26), outline=(145, 116, 60), width=2)
    draw.text((647, box_y1 + 24), "CHARM POINTS", fill=silver, font=font_stat_label)
    draw.text((647, box_y1 + 68), f"{charm:,} PTS", fill=cream, font=font_stat_val)

    # Footer
    draw.line([(92, 565), (w - 92, 565)], fill=(95, 78, 44), width=1)
    ref_display = f"REFERRAL CODE: {ref_code}" if ref_code else "AUTHENTICATED BY HANS CONCIERGE"
    draw.text((92, 595), ref_display, fill=gold, font=font_footer)
    draw.text((w - 360, 595), "@HansVolkovVH_bot", fill=silver, font=font_footer)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def generate_channel_post_card(
    post_type: str,
    post_number: str,
    content: str,
    target_to: str = "",
) -> bytes:
    """Kartu Poster Confession (#confess) & Menfess (#pm) ukuran 1080 x 1350 px."""
    w, h = 1080, 1350
    is_pm = (post_type == "pm")
    img = Image.new("RGB", (w, h), (16, 11, 15))
    draw = ImageDraw.Draw(img)
    _draw_velvet_frame(draw, w, h, is_vip=is_pm)

    gold = (224, 186, 102)
    cream = (245, 239, 230)
    silver = (180, 172, 165)

    font_header = _load_font(28, bold=True)
    font_tag = _load_font(44, bold=True)
    font_to = _load_font(30, bold=True)
    font_footer = _load_font(24, bold=False)

    brand = "THE VELVET HOUR"
    bw = draw.textlength(brand, font=font_header)
    draw.text(((w - bw) / 2, 105), brand, fill=gold, font=font_header)

    label = f"VELVET MENFESS  •  {post_number}" if is_pm else f"MIDNIGHT CONFESSION  •  {post_number}"
    lw = draw.textlength(label, font=font_tag)
    draw.text(((w - lw) / 2, 160), label, fill=cream, font=font_tag)

    draw.line([(140, 240), (w - 140, 240)], fill=gold, width=2)

    cur_y = 285
    if is_pm and target_to:
        safe_to = re.sub(r"\[spoiler\](.+?)\[/spoiler\]", "[SECRET]", target_to, flags=re.IGNORECASE)
        to_line = f"To: {safe_to[:36]}"
        tw = draw.textlength(to_line, font=font_to)
        draw.text(((w - tw) / 2, cur_y), to_line, fill=gold, font=font_to)
        cur_y += 75

    clean_body = re.sub(r"\[spoiler\](.+?)\[/spoiler\]", r"[\1]", content, flags=re.IGNORECASE | re.DOTALL)

    text_len = len(clean_body)
    if text_len <= 140:
        body_size, wrap_width, line_spacing = 42, 32, 62
    elif text_len <= 320:
        body_size, wrap_width, line_spacing = 34, 40, 50
    else:
        body_size, wrap_width, line_spacing = 28, 48, 42

    font_body = _load_font(body_size, bold=False)

    wrapped_lines = []
    for paragraph in clean_body.splitlines():
        if not paragraph.strip():
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(textwrap.wrap(paragraph, width=wrap_width))

    max_lines = 14
    if len(wrapped_lines) > max_lines:
        wrapped_lines = wrapped_lines[:max_lines]
        wrapped_lines[-1] = wrapped_lines[-1][: max(0, len(wrapped_lines[-1]) - 3)] + "..."

    total_text_h = len(wrapped_lines) * line_spacing
    area_top = cur_y + 20
    area_bottom = h - 220
    start_y = max(area_top, area_top + ((area_bottom - area_top - total_text_h) // 2))

    for i, line in enumerate(wrapped_lines):
        lw_line = draw.textlength(line, font=font_body)
        draw.text(((w - lw_line) / 2, start_y + i * line_spacing), line, fill=cream, font=font_body)

    draw.line([(140, h - 180), (w - 140, h - 180)], fill=(120, 96, 50), width=2)
    sig = "— Secret Admirer  |  #pm" if is_pm else "— Anonymous Guest  |  #confess"
    sw = draw.textlength(sig, font=font_footer)
    draw.text(((w - sw) / 2, h - 145), sig, fill=gold, font=font_footer)

    sub_sig = "Kirim pesan rahasia melalui @HansVolkovVH_bot"
    ssw = draw.textlength(sub_sig, font=_load_font(20, bold=False))
    draw.text(((w - ssw) / 2, h - 105), sub_sig, fill=silver, font=_load_font(20, bold=False))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
