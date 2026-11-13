"""
Generate multi-resolution favicon.ico, standard web icons, and Android adaptive maskable icons for Shoppin.

Produces:
- static/images/icon-maskable.svg (Adaptive SVG with 80% safe zone compliance and edge-to-edge solid background)
- static/android-chrome-maskable-192x192.png (purpose: maskable)
- static/android-chrome-maskable-512x512.png (purpose: maskable)
- static/android-chrome-192x192.png (purpose: any)
- static/android-chrome-512x512.png (purpose: any)
- static/apple-touch-icon.png (180x180, solid background to prevent black iOS corners)
- static/favicon-16x16.png
- static/favicon-32x32.png
- static/favicon-48x48.png
- static/favicon.ico (multi-resolution container: 16x16, 32x32, 48x48)
- static/site.webmanifest
"""

from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

STATIC_DIR = Path("static")
IMAGES_DIR = STATIC_DIR / "images"

# Canonical Maskable SVG:
# Features a full-bleed white background (#ffffff) and the 4-row recipe checklist
# + clean-line metal shopping cart scaled and centered within the 80% Safe Zone circle (radius 204.8px)
MASKABLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <rect width="512" height="512" fill="#ffffff"/>
  <g transform="translate(55.5, 51.5) scale(8.0)">
    <!-- Checklist -->
    <rect x="5" y="11" width="3" height="3" fill="#059669"/>
    <rect x="9.5" y="11.5" width="9.5" height="2" fill="#0f172a"/>
    <rect x="5" y="17.5" width="3" height="3" fill="#059669"/>
    <rect x="9.5" y="18" width="9.5" height="2" fill="#0f172a"/>
    <rect x="5" y="24" width="3" height="3" fill="#059669"/>
    <rect x="9.5" y="24.5" width="11" height="2" fill="#0f172a"/>
    <rect x="5" y="30.5" width="3" height="3" fill="#059669"/>
    <rect x="9.5" y="31" width="8.5" height="2" fill="#0f172a"/>
    <!-- Cart -->
    <path d="M21 17h3l2.8 11.5a1.2 1.2 0 0 0 1.2.9h10.5a1.2 1.2 0 0 0 1.2-.9l2.5-8.5H24.5" 
          stroke="#0f172a" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <line x1="29" y1="19" x2="29" y2="27" stroke="#0f172a" stroke-width="1.2" stroke-linecap="butt"/>
    <line x1="33" y1="19" x2="33" y2="27" stroke="#0f172a" stroke-width="1.2" stroke-linecap="butt"/>
    <line x1="37" y1="19" x2="37" y2="26.5" stroke="#0f172a" stroke-width="1.2" stroke-linecap="butt"/>
    <circle cx="29" cy="36" r="2.2" fill="#0f172a"/>
    <circle cx="37" cy="36" r="2.2" fill="#0f172a"/>
  </g>
</svg>"""


def generate_all_icons():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Write the canonical maskable SVG
    maskable_svg_path = IMAGES_DIR / "icon-maskable.svg"
    maskable_svg_path.write_text(MASKABLE_SVG.strip() + "\n", encoding="utf-8")
    print(f"  -> Created {maskable_svg_path}")

    # Read the canonical standard SVG
    standard_svg_path = IMAGES_DIR / "icon.svg"
    if not standard_svg_path.exists():
        raise FileNotFoundError(f"Missing {standard_svg_path}")
    standard_svg = standard_svg_path.read_text(encoding="utf-8")

    # Render PNGs using Chromium for high-fidelity vector rasterization
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")

        # Render standard icons (512x512 master)
        page_std = browser.new_page(viewport={"width": 512, "height": 512})
        page_std.set_content(
            f"<html><body style='margin:0;padding:0;background:transparent;overflow:hidden;'>{standard_svg}</body></html>"
        )
        std_512_path = STATIC_DIR / "android-chrome-512x512.png"
        page_std.screenshot(path=str(std_512_path), omit_background=True)

        # Render maskable icons (512x512 master with solid #ffffff background)
        page_mask = browser.new_page(viewport={"width": 512, "height": 512})
        page_mask.set_content(
            f"<html><body style='margin:0;padding:0;background:#ffffff;overflow:hidden;'>{MASKABLE_SVG}</body></html>"
        )
        mask_512_path = STATIC_DIR / "android-chrome-maskable-512x512.png"
        page_mask.screenshot(path=str(mask_512_path))

        browser.close()

    print(f"  -> Created {std_512_path} (512x512 standard)")
    print(f"  -> Created {mask_512_path} (512x512 maskable)")

    # 2. Generate resized variants
    master_std = Image.open(std_512_path).convert("RGBA")
    master_mask = Image.open(mask_512_path).convert("RGBA")

    # android-chrome-192x192.png (standard)
    std_192_path = STATIC_DIR / "android-chrome-192x192.png"
    master_std.resize((192, 192), Image.Resampling.LANCZOS).save(std_192_path, format="PNG", optimize=True)
    print(f"  -> Created {std_192_path}")

    # android-chrome-maskable-192x192.png (maskable)
    mask_192_path = STATIC_DIR / "android-chrome-maskable-192x192.png"
    master_mask.resize((192, 192), Image.Resampling.LANCZOS).save(mask_192_path, format="PNG", optimize=True)
    print(f"  -> Created {mask_192_path}")

    # apple-touch-icon.png (180x180, on solid white background to prevent black iOS corners)
    apple_path = STATIC_DIR / "apple-touch-icon.png"
    apple_img = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    resized_std_180 = master_std.resize((180, 180), Image.Resampling.LANCZOS)
    apple_img.alpha_composite(resized_std_180)
    apple_img.save(apple_path, format="PNG", optimize=True)
    print(f"  -> Created {apple_path} (180x180 solid background)")

    # Favicons (16, 32, 48)
    for px in [16, 32, 48]:
        fav_path = STATIC_DIR / f"favicon-{px}x{px}.png"
        master_std.resize((px, px), Image.Resampling.LANCZOS).save(fav_path, format="PNG", optimize=True)
        print(f"  -> Created {fav_path}")

    # Multi-resolution favicon.ico container
    ico_path = STATIC_DIR / "favicon.ico"
    ico_sizes = [(16, 16), (32, 32), (48, 48)]
    master_std.save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"  -> Created {ico_path} with sizes: {ico_sizes}")

    # 3. Generate site.webmanifest with separate "any" and "maskable" icons
    manifest_path = STATIC_DIR / "site.webmanifest"
    manifest_content = """{
    "name": "recipe.klopot.tech",
    "short_name": "Recipe",
    "description": "Fast recipe manager, meal planning, and grocery lists by Waldorf Wellington.",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "theme_color": "#059669",
    "background_color": "#ffffff",
    "icons": [
        {
            "src": "/static/images/icon.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "any"
        },
        {
            "src": "/static/android-chrome-192x192.png?v=8",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any"
        },
        {
            "src": "/static/android-chrome-512x512.png?v=8",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any"
        },
        {
            "src": "/static/images/icon-maskable.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "maskable"
        },
        {
            "src": "/static/android-chrome-maskable-192x192.png?v=8",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "maskable"
        },
        {
            "src": "/static/android-chrome-maskable-512x512.png?v=8",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable"
        }
    ]
}
"""
    manifest_path.write_text(manifest_content.strip() + "\n", encoding="utf-8")
    print(f"  -> Created {manifest_path}")


if __name__ == "__main__":
    generate_all_icons()
