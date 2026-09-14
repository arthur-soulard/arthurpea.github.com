"""
appicon.py — Icone de l'app recoloree a la volee selon la couleur d'accent.

L'icone embarquee dans le .exe est figee (ressource Windows, choisie au build).
Ce module en regenere une variante a la couleur d'accent choisie dans l'UI,
puis l'applique :

  * a la fenetre en cours (titre + barre des taches) via WM_SETICON  — immediat
  * aux raccourcis .lnk (Bureau, menu Demarrer, barre des taches epinglee)
    via WScript.Shell, uniquement si l'utilisateur le demande explicitement

Le rendu reprend exactement assets/make_icon.py : carre arrondi, lisere
interne, "P" blanc centre, supersampling 4x + LANCZOS, .ico multi-resolution
a PNG embarques (net de 16 a 256 px).
"""
from __future__ import annotations

import os
import sys
import struct
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Optional

import storage


DEFAULT_COLOR = "#d97706"
_ICON_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

# Handles HICON gardes vivants : Windows lit l'icone tant que la fenetre existe
_LIVE_ICONS = []


# ─── Couleurs ─────────────────────────────────────────────────────────────────

def _norm_color(color: Optional[str]) -> str:
    c = (color or "").strip()
    if c.startswith("#"):
        c = c[1:]
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return DEFAULT_COLOR
    try:
        int(c, 16)
    except ValueError:
        return DEFAULT_COLOR
    return "#" + c.lower()


def _rgb(color: str) -> tuple:
    c = _norm_color(color)[1:]
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _darken(rgb: tuple, factor: float = 0.78) -> tuple:
    return tuple(max(0, min(255, int(round(v * factor)))) for v in rgb)


# ─── Rendu (identique a assets/make_icon.py, mais parametre par la couleur) ────

def _find_bold_font(size: int):
    from PIL import ImageFont
    for c in ("C:/Windows/Fonts/segoeuib.ttf",
              "C:/Windows/Fonts/arialbd.ttf",
              "C:/Windows/Fonts/calibrib.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _render_tile(target_size: int, base: tuple, dark: tuple):
    from PIL import Image, ImageDraw
    SS = 4
    size = target_size * SS
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    radius = int(size * 0.18)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=base)

    if target_size > 32:
        inset = max(2, size // 64)
        d.rounded_rectangle((inset, inset, size - 1 - inset, size - 1 - inset),
                            radius=radius - inset, outline=dark,
                            width=max(2, size // 96))

    p_ratio = 0.62 if target_size >= 64 else 0.72
    font = _find_bold_font(int(size * p_ratio))
    bbox = d.textbbox((0, 0), "P", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - size * 0.02),
           "P", font=font, fill=(255, 255, 255))

    return img.resize((target_size, target_size), Image.Resampling.LANCZOS)


def _build_ico(images_by_size: dict, out_path: Path) -> None:
    """ICONDIR + ICONDIRENTRY[N] + flux PNG (format moderne, net en petit)."""
    sizes = sorted(images_by_size.keys())
    blobs = {}
    for s in sizes:
        buf = BytesIO()
        images_by_size[s].save(buf, format="PNG", optimize=True)
        blobs[s] = buf.getvalue()

    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for s in sizes:
        png = blobs[s]
        b = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    for s in sizes:
        out += blobs[s]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".ico.tmp")
    tmp.write_bytes(bytes(out))
    os.replace(tmp, out_path)


# ─── Cache disque ─────────────────────────────────────────────────────────────

def icons_dir() -> Path:
    d = storage.get_app_dir() / "icones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ico_for(color: str) -> Optional[Path]:
    """
    Retourne le .ico correspondant a la couleur (le genere si absent).
    Retourne None si Pillow n'est pas disponible.
    """
    color = _norm_color(color)
    path = icons_dir() / ("pilote_" + color[1:] + ".ico")
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        base = _rgb(color)
        imgs = {s: _render_tile(s, base, _darken(base)) for s in _ICON_SIZES}
        _build_ico(imgs, path)
        return path
    except Exception as e:
        print(f"[appicon] generation KO ({color}) : {e}", flush=True)
        return None


# ─── Application a la fenetre en cours ────────────────────────────────────────

def _main_hwnd() -> int:
    """HWND de la fenetre principale de CE process."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    pid_here = os.getpid()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == pid_here and user32.IsWindowVisible(hwnd):
            if not user32.GetWindow(hwnd, 4):        # GW_OWNER = 4 -> fenetre racine
                found.append(hwnd)
        return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        pass
    if found:
        return found[0]
    return user32.FindWindowW(None, "Pilote") or 0


def apply_to_window(color: str) -> bool:
    """Change l'icone de la fenetre + de la vignette barre des taches."""
    if sys.platform != "win32":
        return False
    path = ico_for(color)
    if not path:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = _main_hwnd()
        if not hwnd:
            return False

        IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1

        ok = False
        for which, cx, cy in ((ICON_SMALL, 16, 16), (ICON_BIG, 32, 32)):
            h = user32.LoadImageW(None, str(path), IMAGE_ICON, cx, cy,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                _LIVE_ICONS.append(h)
                user32.SendMessageW(hwnd, WM_SETICON, which, h)
                ok = True
        return ok
    except Exception as e:
        print(f"[appicon] application fenetre KO : {e}", flush=True)
        return False


# ─── Application aux raccourcis (Bureau / Demarrer / barre des taches) ────────

def _shortcut_candidates() -> list:
    """Raccourcis .lnk susceptibles de pointer sur Pilote."""
    if sys.platform != "win32":
        return []
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    spots = [
        home / "Desktop",
        Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop",
        appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        appdata / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar",
    ]
    out = []
    for spot in spots:
        if not spot.exists():
            continue
        try:
            for lnk in spot.rglob("*.lnk"):
                name = lnk.stem.lower()
                # Le raccourci de desinstallation garde l'icone d'origine
                if any(x in name for x in ("desinstall", "désinstall", "uninstall")):
                    continue
                if "pilote" in name or "suivi pea" in name or "suivi_pea" in name:
                    out.append(lnk)
        except Exception:
            continue
    return out


def apply_to_shortcuts(color: str) -> dict:
    """
    Repointe l'icone des raccourcis Pilote vers le .ico recolore.
    Passe par WScript.Shell (aucune dependance supplementaire).
    """
    if sys.platform != "win32":
        return {"ok": False, "error": "Windows uniquement", "count": 0}
    path = ico_for(color)
    if not path:
        return {"ok": False, "error": "Pillow indisponible", "count": 0}

    links = _shortcut_candidates()
    if not links:
        return {"ok": False, "error": "aucun raccourci Pilote trouve", "count": 0}

    ps_lines = ["$sh = New-Object -ComObject WScript.Shell"]
    for lnk in links:
        p = str(lnk).replace("'", "''")
        i = str(path).replace("'", "''")
        ps_lines.append(f"$s = $sh.CreateShortcut('{p}'); $s.IconLocation = '{i},0'; $s.Save()")
    # Force Windows a relire le cache d'icones
    ps_lines.append(
        "Add-Type -Namespace W -Name S -MemberDefinition "
        "'[DllImport(\"shell32.dll\")] public static extern void "
        "SHChangeNotify(int e, uint f, IntPtr a, IntPtr b);'; "
        "[W.S]::SHChangeNotify(0x8000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)"
    )

    try:
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", "; ".join(ps_lines)],
            capture_output=True, text=True, timeout=30, creationflags=flags,
        )
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or "powershell KO").strip()[:300], "count": 0}
        return {"ok": True, "count": len(links),
                "paths": [str(l) for l in links], "ico": str(path)}
    except Exception as e:
        return {"ok": False, "error": str(e), "count": 0}
