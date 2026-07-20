from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bean_pudding.generator import build_pattern, build_rgb_pattern
    from bean_pudding.palette import Palette
    from bean_pudding.render import render_pattern
else:
    from .generator import build_pattern, build_rgb_pattern
    from .palette import Palette
    from .render import render_pattern


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PALETTE = PROJECT_ROOT / "data" / "mard_palette.csv"
DEFAULT_INPUT = PROJECT_ROOT / "images" / "test" / "test3.jpg"

# 用户可直接修改的默认参数。
# 输出图最长边的豆格数；另一边按原图比例自动计算。
TARGET_MAX_SIZE = 78
# 最终允许使用的 Mard 色号数量；0 表示不限制，正数表示最多使用该数量。
FINAL_COLOR_LIMIT = 10
# 整张图内相近 RGB 的全局合并阈值，实际使用 LAB 感知色差；0 表示关闭。
# 数值越大，越多颜色会共用同一个 Mard 色号；建议先在 4~8 之间调整。
GLOBAL_COLOR_MERGE_DISTANCE = 6.0

# 是否简化轮廓：统一与空白背景相邻的最外层描边，并尽量清除紧贴外圈的第二层深色；
# 不会主动统一眼睛、嘴巴、领带等内部线条。False 表示完全保留标色后的原轮廓。
OUTLINE_SIMPLIFY = True
# 可被当作深色轮廓的最高亮度，范围可理解为 0~255；数值越大，越多中间色会参与轮廓统一。
OUTLINE_MAX_LUMA = 135.0
# 轮廓与相邻亮色之间需要达到的最小亮度差；越小处理越积极，越大越保守。
OUTLINE_LUMA_GAP = 26.0

# 是否恢复缩图时被两侧深色描边压暗的封闭亮色芯，例如白色绳芯或文字内部留白。
BRIGHT_DETAIL_RECOVERY = True
# 是否按每个豆格在原图中覆盖的完整区域进行复核；当区域主色明确不是白色，
# 但 RGB 缩图或 Mard 标色误变成近白色时，将其恢复为该区域主色。
SOURCE_COVERAGE_RECOVERY = True
# 是否把白色主体附近零散的小块近白过渡色合并回主白色；可减少抗锯齿杂色，
# 但关闭后会保留更多浅灰、米白等细微明暗变化。
NEAR_WHITE_CLEANUP = True


def _write_summary(pattern, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["code", "name", "hex", "r", "g", "b", "count"])
        for code, count in pattern.counts.most_common():
            bead = pattern.colors_by_code[code]
            writer.writerow([code, bead.name, bead.hex, *bead.rgb, count])


def _default_output_paths(input_path: Path) -> tuple[Path, Path, Path]:
    output_dir = PROJECT_ROOT / "outputs" / input_path.stem
    pattern_output = output_dir / f"{input_path.stem}_pattern.jpg"
    rgb_output = output_dir / f"{input_path.stem}_pattern_rgb.jpg"
    summary_output = output_dir / f"{input_path.stem}_summary.csv"
    return pattern_output, rgb_output, summary_output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert an image into a fuse-bead pattern.")
    parser.add_argument("input", type=Path, nargs="?", default=DEFAULT_INPUT, help="Input image path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Pattern output path. Defaults to outputs/INPUT_NAME/INPUT_NAME_pattern.jpg.",
    )
    parser.add_argument(
        "--rgb-output",
        type=Path,
        default=None,
        help="Output path for the pre-label RGB pixel chart. Defaults to OUTPUT stem + _rgb.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Summary CSV path. Defaults to outputs/INPUT_NAME/INPUT_NAME_summary.csv.",
    )
    parser.add_argument("--palette", type=Path, default=DEFAULT_PALETTE)
    parser.add_argument(
        "--exclude-colors",
        default="",
        help="Comma-separated bead codes excluded from matching; use an empty string to disable.",
    )
    parser.add_argument("--title", default="拼豆图纸")
    parser.add_argument("--max-size", type=int, default=TARGET_MAX_SIZE, help="Maximum width/height in beads.")
    parser.add_argument("--width", type=int, default=None, help="Exact bead width.")
    parser.add_argument("--height", type=int, default=None, help="Exact bead height.")
    parser.add_argument(
        "--denoise",
        choices=["none", "median", "smooth", "edge", "bilateral"],
        default="edge",
        help="Clean small color noise before resizing.",
    )
    parser.add_argument(
        "--denoise-strength",
        type=int,
        default=2,
        help="Denoise strength before resizing; 0 disables the selected method.",
    )
    parser.add_argument(
        "--denoise-contrast",
        type=float,
        default=1.18,
        help="Contrast recovery after denoise; 1.0 leaves contrast unchanged.",
    )
    parser.add_argument(
        "--denoise-sharpness",
        type=float,
        default=1.35,
        help="Sharpness recovery after denoise; 1.0 leaves sharpness unchanged.",
    )
    parser.add_argument(
        "--bright-detail-recovery",
        action=argparse.BooleanOptionalAction,
        default=BRIGHT_DETAIL_RECOVERY,
        help="Restore enclosed near-white details darkened by neighboring outlines during resizing.",
    )
    parser.add_argument(
        "--source-coverage-recovery",
        action=argparse.BooleanOptionalAction,
        default=SOURCE_COVERAGE_RECOVERY,
        help="Recover a confident non-white source-region majority when resizing produces near-white.",
    )
    parser.add_argument(
        "--pre-colors",
        type=int,
        default=12,
        help="Merge similar source-image colors before resizing; use 0 to disable.",
    )
    parser.add_argument(
        "--pre-mode-filter-size",
        type=int,
        default=0,
        help="Local mode filter size before resizing; use 0 to disable.",
    )
    parser.add_argument("--max-colors", type=int, default=0, help="Limit source image colors before bead matching.")
    parser.add_argument(
        "--palette-limit",
        type=int,
        default=FINAL_COLOR_LIMIT,
        help="Limit final bead matching to at most this many Mard colors; 0 means unlimited.",
    )
    parser.add_argument(
        "--global-color-merge-distance",
        type=float,
        default=GLOBAL_COLOR_MERGE_DISTANCE,
        help="Group similar RGB colors across the whole image before Mard matching; 0 disables it.",
    )
    parser.add_argument(
        "--dominant-snap-distance",
        type=float,
        default=14.0,
        help="Prefer common bead colors within this LAB distance during global labeling; use 0 to disable.",
    )
    parser.add_argument(
        "--dominant-snap-penalty",
        type=float,
        default=3.0,
        help="A common color can replace the nearest color only within this extra LAB error.",
    )
    parser.add_argument(
        "--local-merge-distance",
        type=float,
        default=14.0,
        help="Merge adjacent bead colors within this LAB distance after labeling; use 0 to disable.",
    )
    parser.add_argument(
        "--local-merge-threshold",
        type=int,
        default=2,
        help="Neighbor count needed before a similar local color can replace the current bead.",
    )
    parser.add_argument(
        "--local-merge-passes",
        type=int,
        default=1,
        help="Number of local similar-color merge passes after labeling.",
    )
    parser.add_argument(
        "--near-white-cleanup",
        action=argparse.BooleanOptionalAction,
        default=NEAR_WHITE_CLEANUP,
        help="Merge small near-white transition clusters into the dominant adjacent white.",
    )
    parser.add_argument(
        "--outline-simplify",
        action=argparse.BooleanOptionalAction,
        default=OUTLINE_SIMPLIFY,
        help="Unify the outermost one-cell boundary without changing internal details.",
    )
    parser.add_argument(
        "--outline-max-luma",
        type=float,
        default=OUTLINE_MAX_LUMA,
        help="Maximum luminance used when choosing the main outline color.",
    )
    parser.add_argument(
        "--outline-luma-gap",
        type=float,
        default=OUTLINE_LUMA_GAP,
        help="Minimum luminance gap for replacing a bright outer-edge halo.",
    )
    parser.add_argument(
        "--detail-min-share",
        type=float,
        default=0.0,
        help="Protect a high-contrast detail color when it covers at least this share of a bead region.",
    )
    parser.add_argument(
        "--detail-luma-gap",
        type=float,
        default=38.0,
        help="Protect detail only when it is this much darker than the region average.",
    )
    parser.add_argument(
        "--detail-max-luma",
        type=float,
        default=105.0,
        help="Protect detail only when its luminance is no brighter than this value.",
    )
    parser.add_argument(
        "--detail-base-min-luma",
        type=float,
        default=205.0,
        help="Allow dark detail replacement only when the normal bead color is at least this bright.",
    )
    parser.add_argument(
        "--pixel-method",
        choices=["global", "vote", "resize"],
        default="global",
        help="Use Photoshop-like global mapping, region voting, or the old resize-based method.",
    )
    parser.add_argument(
        "--vote-threshold",
        type=float,
        default=0.35,
        help="Use a region's most common bead color when its vote share reaches this value.",
    )
    parser.add_argument(
        "--min-region-pixels",
        type=int,
        default=1,
        help="Leave a bead blank when fewer non-background source pixels fall in its region.",
    )
    parser.add_argument("--cell-size", type=int, default=20, help="Rendered pixel size of one bead cell.")
    parser.add_argument(
        "--empty-background",
        choices=["corners", "white", "none"],
        default="corners",
        help="Pixels close to the corner color can be left blank.",
    )
    parser.add_argument("--background-threshold", type=float, default=7.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.palette_limit < 0:
        raise ValueError("--palette-limit / FINAL_COLOR_LIMIT must be 0 or a positive integer.")
    if args.global_color_merge_distance < 0:
        raise ValueError("--global-color-merge-distance must be 0 or a positive number.")
    default_output, default_rgb_output, default_summary = _default_output_paths(args.input)
    output = args.output or default_output
    rgb_output = args.rgb_output or default_rgb_output
    summary = args.summary or default_summary
    excluded = {code.strip() for code in args.exclude_colors.split(",") if code.strip()}
    palette = Palette.from_csv(args.palette).without_codes(excluded)
    rgb_pattern = build_rgb_pattern(
        input_path=args.input,
        max_size=args.max_size,
        width=args.width,
        height=args.height,
        empty_background=args.empty_background,
        background_threshold=args.background_threshold,
        denoise_method=args.denoise,
        denoise_strength=args.denoise_strength,
        denoise_contrast=args.denoise_contrast,
        denoise_sharpness=args.denoise_sharpness,
        bright_detail_recovery=args.bright_detail_recovery,
        source_coverage_recovery=args.source_coverage_recovery,
    )
    pattern = build_pattern(
        input_path=args.input,
        palette=palette,
        max_size=args.max_size,
        width=args.width,
        height=args.height,
        max_colors=args.max_colors,
        pre_colors=args.pre_colors,
        pre_mode_filter_size=args.pre_mode_filter_size,
        denoise_method=args.denoise,
        denoise_strength=args.denoise_strength,
        denoise_contrast=args.denoise_contrast,
        denoise_sharpness=args.denoise_sharpness,
        empty_background=args.empty_background,
        background_threshold=args.background_threshold,
        pixel_method=args.pixel_method,
        vote_threshold=args.vote_threshold,
        min_region_pixels=args.min_region_pixels,
        palette_limit=args.palette_limit,
        global_color_merge_distance=args.global_color_merge_distance,
        dominant_snap_distance=args.dominant_snap_distance,
        dominant_snap_penalty=args.dominant_snap_penalty,
        local_merge_distance=args.local_merge_distance,
        local_merge_threshold=args.local_merge_threshold,
        local_merge_passes=args.local_merge_passes,
        near_white_cleanup=args.near_white_cleanup,
        outline_simplify=args.outline_simplify,
        outline_max_luma=args.outline_max_luma,
        outline_luma_gap=args.outline_luma_gap,
        bright_detail_recovery=args.bright_detail_recovery,
        source_coverage_recovery=args.source_coverage_recovery,
        detail_min_share=args.detail_min_share,
        detail_luma_gap=args.detail_luma_gap,
        detail_max_luma=args.detail_max_luma,
        detail_base_min_luma=args.detail_base_min_luma,
    )
    render_pattern(
        rgb_pattern,
        rgb_output,
        title=f"{args.title} RGB像素图",
        cell_size=args.cell_size,
        show_codes=False,
        show_legend=False,
    )
    render_pattern(pattern, output, title=args.title, cell_size=args.cell_size)
    _write_summary(pattern, summary)
    print(f"RGB chart: {rgb_output}")
    print(f"Pattern: {output}")
    print(f"Summary: {summary}")
    print(f"Size: {pattern.width}x{pattern.height}, beads: {sum(pattern.counts.values())}, colors: {len(pattern.counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
