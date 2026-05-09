"""
make_icon.py — Genere l'icone Suivi PEA en .ico multi-resolution HQ.

PROBLEME RESOLU : PIL en mode ICO fait du resize automatique (pas LANCZOS),
ce qui produit des icones flous aux petites tailles. On contourne en
construisant manuellement un .ico avec PNG embarques (format moderne
supporte par Windows depuis Vista).

Resultat : icones nettes a TOUTES les resolutions (16 a 256).
"""

import struct
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent

ORANGE       = (217, 119,   6)
ORANGE_DARK  = (180,  83,   9)
WHITE        = (255, 255, 255)


def find_bold_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_tile(target_size: int) -> Image.Image:
    """Rend l'icone a la taille cible avec supersampling 4x + LANCZOS."""
    SS = 4
    size = target_size * SS
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = int(size * 0.18)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=ORANGE)

    # Lisere interne uniquement aux grandes tailles (sinon ca brouille en petit)
    if target_size > 32:
        inset = max(2, size // 64)
        d.rounded_rectangle(
            (inset, inset, size - 1 - inset, size - 1 - inset),
            radius=radius - inset,
            outline=ORANGE_DARK,
            width=max(2, size // 96),
        )

    # P plus gros aux petites tailles (besoin de remplir l'espace dispo)
    p_ratio = 0.62 if target_size >= 64 else 0.72
    p_size  = int(size * p_ratio)
    p_font  = find_bold_font(p_size)
    p_bbox  = d.textbbox((0, 0), "P", font=p_font)
    p_w = p_bbox[2] - p_bbox[0]; p_h = p_bbox[3] - p_bbox[1]
    x0  = (size - p_w) / 2 - p_bbox[0]
    y0  = (size - p_h) / 2 - p_bbox[1] - size * 0.02
    d.text((x0, y0), "P", font=p_font, fill=WHITE)

    return img.resize((target_size, target_size), Image.Resampling.LANCZOS)


def build_ico_with_png_streams(images_by_size: dict, out_path: Path):
    """
    Construit un .ico ou chaque taille est embarquee en tant que PNG.
    Format ICONDIR + ICONDIRENTRY[N] + datas PNG.
    Chaque ICONDIRENTRY = 16 octets.
    """
    sizes = sorted(images_by_size.keys())
    n = len(sizes)

    # Encode chaque image en PNG en memoire
    png_blobs = {}
    for s in sizes:
        buf = BytesIO()
        images_by_size[s].save(buf, format="PNG", optimize=True)
        png_blobs[s] = buf.getvalue()

    # ICONDIR header (6 octets)
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, n)  # reserved=0, type=1 (ICO), count

    # ICONDIRENTRY (16 octets * n)
    data_offset = 6 + 16 * n
    for s in sizes:
        png = png_blobs[s]
        size_byte = 0 if s >= 256 else s   # 0 dans le format = 256
        out += struct.pack(
            "<BBBBHHII",
            size_byte,    # bWidth
            size_byte,    # bHeight
            0,            # bColorCount (0 = pas de palette)
            0,            # bReserved
            1,            # wPlanes
            32,           # wBitCount (RGBA 32 bit)
            len(png),     # dwBytesInRes
            data_offset,  # dwImageOffset
        )
        data_offset += len(png)

    # Donnees PNG concatenees
    for s in sizes:
        out += png_blobs[s]

    out_path.write_bytes(bytes(out))


def main():
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    images_by_size = {s: render_tile(s) for s in sizes}

    out_ico = HERE / "icon.ico"
    build_ico_with_png_streams(images_by_size, out_ico)
    print(f"[icon] Cree {out_ico} avec {len(sizes)} tailles : {sizes}")
    print(f"[icon] Taille fichier : {out_ico.stat().st_size} octets")

    # Apercu PNG haute def
    big_preview = render_tile(512)
    big_preview.save(HERE / "icon_512.png")

    # Strip de toutes les tailles pour validation visuelle
    strip_sizes = [16, 32, 48, 64, 128, 256]
    strip_w = sum(strip_sizes) + 12 * (len(strip_sizes) - 1)
    strip = Image.new("RGBA", (strip_w, max(strip_sizes)), (255, 255, 255, 255))
    x = 0
    for s in strip_sizes:
        strip.paste(images_by_size[s] if s in images_by_size else render_tile(s), (x, 0))
        x += s + 12
    strip.save(HERE / "icon_strip.png")
    print(f"[icon] Apercu strip : {HERE / 'icon_strip.png'}")


if __name__ == "__main__":
    main()
