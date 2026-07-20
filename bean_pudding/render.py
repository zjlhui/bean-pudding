from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .generator import Pattern


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _text_xy(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
) -> tuple[int, int]:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    return (
        left + ((right - left) - (bbox[2] - bbox[0])) // 2,
        top + ((bottom - top) - (bbox[3] - bbox[1])) // 2 - 1,
    )


def render_pattern(
    pattern: Pattern,
    output_path: Path,
    title: str = "拼豆图纸",
    cell_size: int = 20,
    major_every: int = 5,
    show_codes: bool = True,
    show_legend: bool = True,
) -> None:
    label = max(34, int(cell_size * 1.55))
    top_title = 62
    grid_w = pattern.width * cell_size
    grid_h = pattern.height * cell_size
    legend_item_w = max(145, cell_size * 7)
    legend_h = 48 * max(1, ((len(pattern.counts) + 5) // 6)) if show_legend else 0
    canvas_w = label * 2 + grid_w
    canvas_h = top_title + label + grid_h + label + legend_h + 28

    image = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(image)

    title_font = _load_font(34, bold=True)
    coord_font = _load_font(max(11, int(cell_size * 0.62)), bold=True)
    code_font = _load_font(max(8, int(cell_size * 0.40)), bold=True)
    legend_font = _load_font(15, bold=True)
    small_font = _load_font(12)

    draw.text((label, 12), title, fill=(35, 35, 35), font=title_font)
    brand_text = "Bean Pudding"
    brand_box = draw.textbbox((0, 0), brand_text, font=title_font)
    draw.text(
        (canvas_w - label - (brand_box[2] - brand_box[0]), 14),
        brand_text,
        fill=(35, 35, 35),
        font=title_font,
    )

    grid_x = label
    grid_y = top_title + label
    grid_bg = (248, 248, 248)
    image_grid = (220, 220, 220)
    major_grid = (232, 157, 72)

    draw.rectangle((grid_x, grid_y, grid_x + grid_w, grid_y + grid_h), fill=grid_bg)

    for y, row in enumerate(pattern.pixels):
        for x, bead in enumerate(row):
            if bead is None:
                continue
            left = grid_x + x * cell_size
            top = grid_y + y * cell_size
            right = left + cell_size
            bottom = top + cell_size
            draw.rectangle((left, top, right, bottom), fill=bead.rgb)
            luminance = (0.299 * bead.rgb[0]) + (0.587 * bead.rgb[1]) + (0.114 * bead.rgb[2])
            text_fill = "black" if luminance > 155 else "white"
            if show_codes and cell_size >= 14:
                tx, ty = _text_xy(draw, (left, top, right, bottom), bead.code, code_font)
                draw.text((tx, ty), bead.code, fill=text_fill, font=code_font)

    for x in range(pattern.width + 1):
        line_x = grid_x + x * cell_size
        color = major_grid if x % major_every == 0 else image_grid
        width = 2 if x % major_every == 0 else 1
        draw.line((line_x, grid_y, line_x, grid_y + grid_h), fill=color, width=width)
    for y in range(pattern.height + 1):
        line_y = grid_y + y * cell_size
        color = major_grid if y % major_every == 0 else image_grid
        width = 2 if y % major_every == 0 else 1
        draw.line((grid_x, line_y, grid_x + grid_w, line_y), fill=color, width=width)

    for x in range(pattern.width):
        text = str(x + 1)
        top_box = (grid_x + x * cell_size, top_title, grid_x + (x + 1) * cell_size, grid_y)
        bottom_box = (
            grid_x + x * cell_size,
            grid_y + grid_h,
            grid_x + (x + 1) * cell_size,
            grid_y + grid_h + label,
        )
        draw.text(_text_xy(draw, top_box, text, coord_font), text, fill=(20, 35, 48), font=coord_font)
        draw.text(_text_xy(draw, bottom_box, text, coord_font), text, fill=(20, 35, 48), font=coord_font)

    for y in range(pattern.height):
        text = str(y + 1)
        left_box = (0, grid_y + y * cell_size, grid_x, grid_y + (y + 1) * cell_size)
        right_box = (
            grid_x + grid_w,
            grid_y + y * cell_size,
            canvas_w,
            grid_y + (y + 1) * cell_size,
        )
        draw.text(_text_xy(draw, left_box, text, coord_font), text, fill=(20, 35, 48), font=coord_font)
        draw.text(_text_xy(draw, right_box, text, coord_font), text, fill=(20, 35, 48), font=coord_font)

    if show_legend:
        legend_y = grid_y + grid_h + label + 10
        legend_x = label
        for index, (code, count) in enumerate(pattern.counts.most_common()):
            bead = pattern.colors_by_code[code]
            col = index % 6
            row = index // 6
            x = legend_x + col * legend_item_w
            y = legend_y + row * 48
            draw.rounded_rectangle((x, y, x + legend_item_w - 8, y + 34), radius=4, fill=bead.rgb)
            luminance = (0.299 * bead.rgb[0]) + (0.587 * bead.rgb[1]) + (0.114 * bead.rgb[2])
            fill = "black" if luminance > 155 else "white"
            draw.text((x + 8, y + 7), code, fill=fill, font=legend_font)
            draw.text((x + 56, y + 7), f"({count})", fill=fill, font=legend_font)
            if row == 0:
                draw.text((x + 8, y + 35), bead.name[:18], fill=(80, 80, 80), font=small_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)
