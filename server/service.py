from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from bean_pudding.generator import Pattern, build_pattern, build_rgb_pattern
from bean_pudding.palette import Palette
from bean_pudding.render import render_pattern


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PALETTE_PATH = PROJECT_ROOT / "data" / "mard_palette.csv"
MAX_SOURCE_SIDE = 2048
MAX_SOURCE_PIXELS = 40_000_000


@dataclass(frozen=True)
class GenerationOptions:
    max_size: int = 78
    color_limit: int = 10
    global_color_merge_distance: float = 6.0
    outline_simplify: bool = True
    bright_detail_recovery: bool = True
    source_coverage_recovery: bool = True
    near_white_cleanup: bool = True
    title: str = "拼豆图纸"


@dataclass(frozen=True)
class SourceInfo:
    width: int
    height: int
    resized: bool


@dataclass(frozen=True)
class GenerationResult:
    width: int
    height: int
    bead_count: int
    color_count: int
    pattern_path: Path
    rgb_path: Path
    summary_path: Path
    summary: list[dict[str, object]]
    source: SourceInfo


def validate_options(options: GenerationOptions) -> None:
    if not 16 <= options.max_size <= 78:
        raise ValueError("最大边长必须在 16 到 78 之间。")
    if not 0 <= options.color_limit <= 64:
        raise ValueError("颜色上限必须在 0 到 64 之间，0 表示不限制。")
    if not 0.0 <= options.global_color_merge_distance <= 30.0:
        raise ValueError("相似色合并阈值必须在 0 到 30 之间。")
    if not options.title.strip():
        raise ValueError("图纸标题不能为空。")
    if len(options.title) > 30:
        raise ValueError("图纸标题不能超过 30 个字符。")


def normalize_source(source_path: Path, output_path: Path) -> SourceInfo:
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    try:
        with Image.open(source_path) as opened:
            opened.verify()
        with Image.open(source_path) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.width * image.height > MAX_SOURCE_PIXELS:
                raise ValueError("图片像素过大，请选择不超过 4000 万像素的图片。")

            original_size = image.size
            image.thumbnail((MAX_SOURCE_SIDE, MAX_SOURCE_SIDE), Image.Resampling.LANCZOS)
            resized = image.size != original_size
            normalized = image.convert("RGBA")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            normalized.save(output_path, format="PNG", optimize=True)
            return SourceInfo(width=normalized.width, height=normalized.height, resized=resized)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("无法读取该图片，请使用 JPG、PNG 或 WebP 图片。") from error


def _summary_rows(pattern: Pattern) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for code, count in pattern.counts.most_common():
        bead = pattern.colors_by_code[code]
        rows.append(
            {
                "code": code,
                "name": bead.name,
                "hex": bead.hex,
                "rgb": list(bead.rgb),
                "count": count,
            }
        )
    return rows


def _write_summary(rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["code", "name", "hex", "r", "g", "b", "count"])
        for row in rows:
            rgb = row["rgb"]
            writer.writerow([row["code"], row["name"], row["hex"], *rgb, row["count"]])


def generate_pattern_files(
    source_path: Path,
    output_dir: Path,
    options: GenerationOptions,
    palette_path: Path = DEFAULT_PALETTE_PATH,
) -> GenerationResult:
    validate_options(options)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = output_dir / "source.png"
    source_info = normalize_source(source_path, normalized_path)
    palette = Palette.from_csv(palette_path)

    rgb_pattern = build_rgb_pattern(
        input_path=normalized_path,
        max_size=options.max_size,
        denoise_method="edge",
        denoise_strength=2,
        denoise_contrast=1.18,
        denoise_sharpness=1.35,
        empty_background="corners",
        background_threshold=7.0,
        bright_detail_recovery=options.bright_detail_recovery,
        source_coverage_recovery=options.source_coverage_recovery,
    )
    pattern = build_pattern(
        input_path=normalized_path,
        palette=palette,
        max_size=options.max_size,
        pre_colors=12,
        denoise_method="edge",
        denoise_strength=2,
        denoise_contrast=1.18,
        denoise_sharpness=1.35,
        empty_background="corners",
        background_threshold=7.0,
        pixel_method="global",
        palette_limit=options.color_limit,
        global_color_merge_distance=options.global_color_merge_distance,
        dominant_snap_distance=14.0,
        dominant_snap_penalty=3.0,
        local_merge_distance=14.0,
        local_merge_threshold=2,
        local_merge_passes=1,
        near_white_cleanup=options.near_white_cleanup,
        outline_simplify=options.outline_simplify,
        outline_max_luma=135.0,
        outline_luma_gap=26.0,
        bright_detail_recovery=options.bright_detail_recovery,
        source_coverage_recovery=options.source_coverage_recovery,
    )

    pattern_path = output_dir / "pattern.jpg"
    rgb_path = output_dir / "pattern_rgb.jpg"
    summary_path = output_dir / "summary.csv"
    render_pattern(
        rgb_pattern,
        rgb_path,
        title=f"{options.title} RGB像素图",
        cell_size=20,
        show_codes=False,
        show_legend=False,
    )
    render_pattern(pattern, pattern_path, title=options.title, cell_size=20)

    summary = _summary_rows(pattern)
    _write_summary(summary, summary_path)
    normalized_path.unlink(missing_ok=True)
    return GenerationResult(
        width=pattern.width,
        height=pattern.height,
        bead_count=sum(pattern.counts.values()),
        color_count=len(pattern.counts),
        pattern_path=pattern_path,
        rgb_path=rgb_path,
        summary_path=summary_path,
        summary=summary,
        source=source_info,
    )
