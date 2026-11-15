"""Generate synthetic demo images for ASTRA-Med's 3 CV modes."""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "demo_samples"


def generate_ultrasound(path: Path) -> None:
    width, height = 512, 384
    img = Image.new("L", (width, height), 14)
    draw = ImageDraw.Draw(img)

    # Sector cone background
    draw.polygon([(256, 20), (40, 355), (472, 355)], fill=42)

    # Horizontal pleural line near top of lung field
    draw.line([(165, 95), (347, 95)], fill=230, width=6)

    # Simulated vertical B-line cluster (bright vertical beams)
    for x_pos in (210, 232, 265, 290):
        for y in range(96, 330, 3):
            intensity = max(90, 225 - int((y - 96) * 0.45))
            draw.line([(x_pos, y), (x_pos + 3, y + 2)], fill=intensity, width=3)

    # Add realistic ultrasound speckle texture
    rng = random.Random(42)
    pixels = img.load()
    for y in range(25, 355):
        for x in range(45, 470):
            val = pixels[x, y]
            if val > 20:
                noise = rng.randint(-18, 18)
                pixels[x, y] = max(0, min(255, val + noise))

    img = img.filter(ImageFilter.GaussianBlur(radius=0.8)).convert("RGB")
    img.save(path)


def generate_skin_eye(path: Path) -> None:
    width, height = 480, 360
    # Warm natural skin tone background
    img = Image.new("RGB", (width, height), (218, 174, 152))
    draw = ImageDraw.Draw(img)

    # Subtle skin texture
    rng = random.Random(7)
    for _ in range(900):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        draw.point((x, y), fill=(205, 160, 140))

    # Erythema / rash region in center-right
    draw.ellipse((175, 110, 315, 235), fill=(210, 88, 82))
    draw.ellipse((205, 135, 285, 205), fill=(224, 62, 62))
    for _ in range(18):
        px = rng.randint(185, 305)
        py = rng.randint(120, 225)
        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=(195, 42, 48))

    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))
    img.save(path)


def generate_device_ocr(path: Path) -> None:
    width, height = 420, 260
    # Dark handheld meter casing
    img = Image.new("RGB", (width, height), (28, 34, 44))
    draw = ImageDraw.Draw(img)

    # High-contrast backlit LCD rectangle
    draw.rounded_rectangle(
        (45, 38, 375, 205),
        radius=14,
        fill=(215, 232, 212),
        outline=(90, 115, 130),
        width=4,
    )

    font_big = None
    font_small = None
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            font_big = ImageFont.truetype(candidate, 84)
            font_small = ImageFont.truetype(candidate, 24)
            break
    if font_big is None:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw.text((115, 68), "138", fill=(18, 28, 22), font=font_big)
    draw.text((285, 158), "mg/dL", fill=(32, 48, 38), font=font_small)
    draw.text((62, 48), "GLUCOSE", fill=(45, 65, 55), font=font_small)

    img.save(path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_ultrasound(OUT_DIR / "sample_ultrasound.png")
    generate_skin_eye(OUT_DIR / "sample_skin_eye.png")
    generate_device_ocr(OUT_DIR / "sample_device_ocr.png")
    print(f"Generated 3 demo images in {OUT_DIR}")


if __name__ == "__main__":
    main()
