"""
Generate multi-resolution favicon.ico and accompanying web icons for Shoppin.

Produces:
- static/favicon.ico (multi-resolution container: 16x16, 32x32, 48x48, 64x64)
- static/favicon-16x16.png
- static/favicon-32x32.png
- static/favicon-48x48.png
- static/apple-touch-icon.png (180x180)
- static/android-chrome-192x192.png (192x192)
- static/android-chrome-512x512.png (512x512)
- static/site.webmanifest
"""

from pathlib import Path

from PIL import Image, ImageDraw


def create_master_icon(size: int = 1024) -> Image.Image:
    """
    Render a high-resolution 1024x1024 master icon for Shoppin.
    Features an emerald squircle badge with a crisp white shopping cart
    and fresh grocery produce peaking out of the basket.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # 1. Background Badge: Smooth Squircle (Rounded Rectangle)
    pad = 48
    radius = 210
    badge_rect = [pad, pad, size - pad, size - pad]

    # Create gradient background
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)

    # Vertical gradient: #10b981 (top) to #047857 (bottom)
    for y in range(pad, size - pad):
        factor = (y - pad) / float(size - 2 * pad)
        r = int(16 * (1 - factor) + 4 * factor)
        g = int(185 * (1 - factor) + 120 * factor)
        b = int(129 * (1 - factor) + 87 * factor)
        bg_draw.line([(pad, y), (size - pad, y)], fill=(r, g, b, 255))

    # Mask with rounded rectangle
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(badge_rect, radius=radius, fill=255)

    # Composite gradient badge onto canvas
    img.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(img)

    # Inner subtle rim highlight
    draw.rounded_rectangle(badge_rect, radius=radius, outline=(255, 255, 255, 60), width=6)

    # 2. Grocery Produce in Basket (Peaking out from top)
    # Carrot (Orange #f97316) tilted diagonally
    carrot_body = [
        (480, 420),
        (540, 310),
        (575, 330),
        (510, 430),
    ]
    draw.polygon(carrot_body, fill=(249, 115, 22, 255))
    # Carrot leaves (Bright Green #4ade80)
    draw.line([(550, 315), (570, 260)], fill=(74, 222, 128, 255), width=12)
    draw.line([(560, 320), (595, 275)], fill=(74, 222, 128, 255), width=12)
    draw.line([(540, 315), (540, 265)], fill=(74, 222, 128, 255), width=10)

    # Golden Citrus Fruit / Apple (Yellow-Gold #fbbf24)
    fruit_bbox = [390, 340, 490, 440]
    draw.ellipse(fruit_bbox, fill=(251, 191, 36, 255))
    # Fruit leaf
    draw.ellipse([435, 320, 465, 345], fill=(34, 197, 94, 255))

    # Fresh Leafy Sprout (Emerald-Green #22c55e) on the right
    draw.ellipse([580, 360, 670, 440], fill=(239, 68, 68, 255))  # Red apple / tomato
    draw.ellipse([620, 340, 645, 365], fill=(74, 222, 128, 255))

    # 3. Shopping Cart Wireframe
    white = (255, 255, 255, 255)
    cart_line_width = 46

    # Cart Handle & Spine
    # Handle grip
    draw.line([(220, 330), (280, 410)], fill=white, width=cart_line_width)
    # Back diagonal spine
    draw.line([(280, 410), (345, 635)], fill=white, width=cart_line_width)
    # Bottom chassis support bar
    draw.line([(345, 635), (745, 635)], fill=white, width=cart_line_width)

    # Basket Outer Frame
    # Top rim
    draw.line([(310, 430), (795, 430)], fill=white, width=cart_line_width)
    # Front angled slope
    draw.line([(795, 430), (725, 615)], fill=white, width=cart_line_width)
    # Bottom basket floor
    draw.line([(725, 615), (360, 615)], fill=white, width=cart_line_width)

    # Basket Grid Lines (Horizontal & Vertical)
    grid_width = 24
    # Horizontal wire
    draw.line([(340, 520), (760, 520)], fill=white, width=grid_width)
    # Vertical wires
    draw.line([(450, 430), (450, 615)], fill=white, width=grid_width)
    draw.line([(555, 430), (555, 615)], fill=white, width=grid_width)
    draw.line([(660, 430), (660, 615)], fill=white, width=grid_width)

    # 4. Cart Wheels (Two solid white wheels with center cutout)
    wheel_radius = 58
    hub_radius = 20

    wheel_centers = [(415, 745), (675, 745)]
    for cx, cy in wheel_centers:
        # Outer wheel rim
        draw.ellipse(
            [cx - wheel_radius, cy - wheel_radius, cx + wheel_radius, cy + wheel_radius],
            fill=white,
        )
        # Inner hub cutout (showing background color for realism)
        draw.ellipse(
            [cx - hub_radius, cy - hub_radius, cx + hub_radius, cy + hub_radius],
            fill=(4, 120, 87, 255),
        )

    return img


def generate_all_icons():
    """Build all icon variants and output to static/."""
    static_dir = Path("static")
    static_dir.mkdir(parents=True, exist_ok=True)

    master = create_master_icon(1024)

    # Target PNG sizes
    png_sizes = {
        "favicon-16x16.png": 16,
        "favicon-32x32.png": 32,
        "favicon-48x48.png": 48,
        "apple-touch-icon.png": 180,
        "android-chrome-192x192.png": 192,
        "android-chrome-512x512.png": 512,
    }

    print("Generating PNG icons...")
    for filename, px in png_sizes.items():
        out_path = static_dir / filename
        resized = master.resize((px, px), Image.Resampling.LANCZOS)
        resized.save(out_path, format="PNG", optimize=True)
        print(f"  -> Created {out_path} ({px}x{px})")

    # Generate multi-resolution favicon.ico container
    # Standard ICO sizes: 16x16, 32x32, 48x48, 64x64, 128x128, 256x256
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = static_dir / "favicon.ico"
    master.save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"  -> Created multi-resolution {ico_path} with sizes: {ico_sizes}")

    # Generate site.webmanifest
    manifest_path = static_dir / "site.webmanifest"
    manifest_content = """{
    "name": "Shoppin",
    "short_name": "Shoppin",
    "icons": [
        {
            "src": "/static/android-chrome-192x192.png",
            "sizes": "192x192",
            "type": "image/png"
        },
        {
            "src": "/static/android-chrome-512x512.png",
            "sizes": "512x512",
            "type": "image/png"
        }
    ],
    "theme_color": "#059669",
    "background_color": "#ffffff",
    "display": "standalone"
}
"""
    manifest_path.write_text(manifest_content.strip() + "\n", encoding="utf-8")
    print(f"  -> Created {manifest_path}")


if __name__ == "__main__":
    generate_all_icons()
