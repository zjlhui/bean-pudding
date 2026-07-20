from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import hypot
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

from .color import lab_distance, rgb_to_lab
from .palette import BeadColor, Palette


@dataclass(frozen=True)
class Pattern:
    width: int
    height: int
    pixels: list[list[BeadColor | None]]
    counts: Counter[str]
    colors_by_code: dict[str, BeadColor]


@dataclass(frozen=True)
class _SourceRegionGuide:
    rgb: tuple[int, int, int]
    share: float
    global_share: float


_SOURCE_GUIDE_COLORS = 12
_SOURCE_GUIDE_MIN_SHARE = 0.44
_SOURCE_GUIDE_MIN_GLOBAL_SHARE = 0.02
_NEAR_WHITE_MIN_LAB_L = 88.0
_NEAR_WHITE_MAX_CHROMA = 3.5
_SOURCE_DARK_MAX_LAB_L = 72.0
_SOURCE_COLOR_MIN_CHROMA = 4.5
_SOURCE_COLOR_MIN_DISTANCE = 4.0
_GLOBAL_GROUP_VOTE_FLOOR = 0.50


def make_rgb_bead(code: str, rgb: tuple[int, int, int]) -> BeadColor:
    hex_color = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
    return BeadColor(code=code, name=code, hex=hex_color, rgb=rgb, brand="RGB")


def _target_size(image: Image.Image, max_size: int, width: int | None, height: int | None) -> tuple[int, int]:
    if width and height:
        return width, height
    if width:
        ratio = width / image.width
        return width, max(1, round(image.height * ratio))
    if height:
        ratio = height / image.height
        return max(1, round(image.width * ratio)), height

    scale = min(max_size / image.width, max_size / image.height, 1.0)
    return max(1, round(image.width * scale)), max(1, round(image.height * scale))


def _quantize(image: Image.Image, max_colors: int | None) -> Image.Image:
    if not max_colors or max_colors <= 0:
        return image.convert("RGBA")
    rgb = image.convert("RGB")
    quantized = rgb.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
    return quantized.convert("RGBA")


def _denoise_source(
    image: Image.Image,
    method: str,
    strength: int,
    contrast: float,
    sharpness: float,
) -> Image.Image:
    image = image.convert("RGBA")
    if method == "none" or strength <= 0:
        return image

    alpha = image.getchannel("A")
    rgb = image.convert("RGB")

    if method == "median":
        size = max(3, min(9, strength * 2 + 1))
        if size % 2 == 0:
            size += 1
        filtered = rgb.filter(ImageFilter.MedianFilter(size=size))
    elif method == "smooth":
        filtered = rgb
        for _ in range(max(1, strength)):
            filtered = filtered.filter(ImageFilter.SMOOTH_MORE)
    elif method == "edge":
        smoothed = rgb
        for _ in range(max(1, strength)):
            smoothed = smoothed.filter(ImageFilter.SMOOTH_MORE)

        edge_mask = rgb.convert("L").filter(ImageFilter.FIND_EDGES)
        edge_mask = ImageOps.autocontrast(edge_mask).filter(ImageFilter.GaussianBlur(radius=1.0))
        edge_mask = ImageEnhance.Contrast(edge_mask).enhance(1.8)
        restored = ImageChops.composite(rgb, smoothed, edge_mask)
        filtered = Image.blend(smoothed, restored, 0.75)
    elif method == "bilateral":
        try:
            import cv2  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "The bilateral denoise mode requires opencv-python and numpy. "
                "Install them or use --denoise median/smooth/none."
            ) from exc

        array = np.array(rgb)
        diameter = max(3, min(15, strength * 2 + 3))
        sigma = max(25, strength * 25)
        filtered = Image.fromarray(cv2.bilateralFilter(array, diameter, sigma, sigma))
    else:
        raise ValueError(f"Unsupported denoise method: {method}")

    if contrast != 1.0:
        filtered = ImageEnhance.Contrast(filtered).enhance(contrast)
    if sharpness != 1.0:
        filtered = ImageEnhance.Sharpness(filtered).enhance(sharpness)

    filtered.putalpha(alpha)
    return filtered


def _recount_rows(rows: list[list[BeadColor | None]]) -> tuple[Counter[str], dict[str, BeadColor]]:
    counts: Counter[str] = Counter()
    colors_by_code: dict[str, BeadColor] = {}
    for row in rows:
        for bead in row:
            if bead is None:
                continue
            counts[bead.code] += 1
            colors_by_code[bead.code] = bead
    return counts, colors_by_code


def _neighbor_points(x: int, y: int, width: int, height: int) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx = x + dx
            ny = y + dy
            if 0 <= nx < width and 0 <= ny < height:
                points.append((nx, ny))
    return points


def _group_similar_rgb_colors(
    counts: Counter[tuple[int, int, int]],
    distance: float,
) -> dict[tuple[int, int, int], tuple[int, int, int]]:
    if distance <= 0:
        return {rgb: rgb for rgb in counts}

    ordered_colors = sorted(counts, key=lambda rgb: (-counts[rgb], rgb))
    labs = {rgb: rgb_to_lab(rgb) for rgb in ordered_colors}
    anchors: list[tuple[int, int, int]] = []
    groups: dict[tuple[int, int, int], tuple[int, int, int]] = {}

    for rgb in ordered_colors:
        best: tuple[float, tuple[int, int, int]] | None = None
        for anchor in anchors:
            color_distance = lab_distance(labs[rgb], labs[anchor])
            candidate = (color_distance, anchor)
            if color_distance <= distance and (best is None or candidate < best):
                best = candidate
        if best is not None:
            groups[rgb] = best[1]
            continue
        anchors.append(rgb)
        groups[rgb] = rgb
    return groups


def _choose_global_group_bead(
    group_rgb: tuple[int, int, int],
    votes: Counter[BeadColor],
    global_counts: Counter[BeadColor],
) -> BeadColor:
    maximum_votes = max(votes.values())
    eligible = [
        bead
        for bead, count in votes.items()
        if count >= maximum_votes * _GLOBAL_GROUP_VOTE_FLOOR
    ]
    group_lab = rgb_to_lab(group_rgb)
    return min(
        eligible,
        key=lambda bead: (
            -global_counts[bead],
            -votes[bead],
            lab_distance(group_lab, bead.lab),
            bead.code,
        ),
    )


def _local_merge_similar_colors(
    rows: list[list[BeadColor | None]],
    distance: float,
    threshold: int,
    passes: int,
) -> list[list[BeadColor | None]]:
    if distance <= 0 or threshold <= 0 or passes <= 0:
        return rows

    height = len(rows)
    width = len(rows[0]) if rows else 0
    current = rows
    for _ in range(passes):
        changed = False
        next_rows = [row.copy() for row in current]
        for y in range(height):
            for x in range(width):
                bead = current[y][x]
                if bead is None:
                    continue

                neighbor_counts: Counter[BeadColor] = Counter()
                for nx, ny in _neighbor_points(x, y, width, height):
                    neighbor = current[ny][nx]
                    if neighbor is None or neighbor.code == bead.code:
                        continue
                    if lab_distance(bead.lab, neighbor.lab) <= distance:
                        neighbor_counts[neighbor] += 1

                if not neighbor_counts:
                    continue
                replacement, count = neighbor_counts.most_common(1)[0]
                if count >= threshold:
                    next_rows[y][x] = replacement
                    changed = True

        current = next_rows
        if not changed:
            break
    return current


def _merge_small_near_white_components(
    rows: list[list[BeadColor | None]],
    enabled: bool,
    max_component_size: int = 24,
    distance: float = 10.0,
    dominance_ratio: float = 3.0,
) -> list[list[BeadColor | None]]:
    if not enabled or not rows:
        return rows

    height = len(rows)
    width = len(rows[0])
    counts, colors_by_code = _recount_rows(rows)
    merged = [row.copy() for row in rows]
    seen: set[tuple[int, int]] = set()

    for y in range(height):
        for x in range(width):
            bead = rows[y][x]
            if bead is None or (x, y) in seen:
                continue
            if _luminance(bead.rgb) < 225.0 or max(bead.rgb) - min(bead.rgb) > 18:
                continue

            component = {(x, y)}
            seen.add((x, y))
            stack = [(x, y)]
            while stack:
                px, py = stack.pop()
                for nx, ny in _neighbor_points(px, py, width, height):
                    neighbor = rows[ny][nx]
                    if (nx, ny) in seen or neighbor is None:
                        continue
                    if neighbor.code == bead.code:
                        seen.add((nx, ny))
                        component.add((nx, ny))
                        stack.append((nx, ny))

            if len(component) > max_component_size:
                continue

            boundary_counts: Counter[BeadColor] = Counter()
            for px, py in component:
                for nx, ny in _neighbor_points(px, py, width, height):
                    if (nx, ny) in component:
                        continue
                    neighbor = rows[ny][nx]
                    if neighbor is None or neighbor.code == bead.code:
                        continue
                    if _luminance(neighbor.rgb) < 225.0:
                        continue
                    if max(neighbor.rgb) - min(neighbor.rgb) > 18:
                        continue
                    if lab_distance(bead.lab, neighbor.lab) <= distance:
                        boundary_counts[neighbor] += 1

            if boundary_counts:
                replacement = min(
                    boundary_counts,
                    key=lambda color: (
                        -boundary_counts[color],
                        -counts[color.code],
                        color.code,
                    ),
                )
            elif len(component) <= 2:
                global_candidates = [
                    color
                    for color in colors_by_code.values()
                    if color.code != bead.code
                    and _luminance(color.rgb) >= 225.0
                    and max(color.rgb) - min(color.rgb) <= 18
                    and lab_distance(bead.lab, color.lab) <= distance
                ]
                if not global_candidates:
                    continue
                replacement = min(
                    global_candidates,
                    key=lambda color: (-counts[color.code], color.code),
                )
            else:
                continue
            if counts[replacement.code] < counts[bead.code] * dominance_ratio:
                continue
            for px, py in component:
                merged[py][px] = replacement

    return merged


def _outline_cell_kind(
    rows: list[list[BeadColor | None]],
    x: int,
    y: int,
    luma_gap: float,
) -> str | None:
    bead = rows[y][x]
    if bead is None:
        return None

    height = len(rows)
    width = len(rows[0]) if rows else 0
    bead_luma = _luminance(bead.rgb)
    internal_edge = False
    for nx, ny in _neighbor_points(x, y, width, height):
        neighbor = rows[ny][nx]
        if neighbor is None:
            return "external"
        if bead_luma + luma_gap <= _luminance(neighbor.rgb):
            internal_edge = True
    return "internal" if internal_edge else None


def _major_foreground_points(
    rows: list[list[BeadColor | None]],
) -> set[tuple[int, int]]:
    height = len(rows)
    width = len(rows[0]) if rows else 0
    remaining = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if rows[y][x] is not None
    }
    components: list[set[tuple[int, int]]] = []
    while remaining:
        start = remaining.pop()
        component = {start}
        stack = [start]
        while stack:
            x, y = stack.pop()
            for point in _neighbor_points(x, y, width, height):
                if point in remaining:
                    remaining.remove(point)
                    component.add(point)
                    stack.append(point)
        components.append(component)

    if not components:
        return set()

    minimum_size = max(1, int(max(map(len, components)) * 0.2))
    return set().union(*(component for component in components if len(component) >= minimum_size))


def _thin_second_outline_layer(
    source_rows: list[list[BeadColor | None]],
    simplified_rows: list[list[BeadColor | None]],
    outline_points: set[tuple[int, int]],
    max_luma: float,
    luma_gap: float,
) -> list[list[BeadColor | None]]:
    height = len(source_rows)
    width = len(source_rows[0]) if source_rows else 0
    major_points = _major_foreground_points(source_rows)
    if not major_points:
        return simplified_rows

    thinned = [row.copy() for row in simplified_rows]
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for x, y in major_points - outline_points:
        bead = source_rows[y][x]
        if bead is None or _luminance(bead.rgb) > max_luma:
            continue

        bead_luma = _luminance(bead.rgb)
        opposed_colors: set[BeadColor] = set()
        for dx, dy in directions:
            outer_point = (x - dx, y - dy)
            inner_point = (x + dx, y + dy)
            if outer_point not in outline_points or inner_point not in major_points:
                continue
            if inner_point in outline_points:
                continue
            inner = source_rows[inner_point[1]][inner_point[0]]
            if inner is not None and _luminance(inner.rgb) >= bead_luma + luma_gap:
                opposed_colors.add(inner)

        if not opposed_colors:
            continue

        inward_counts: Counter[BeadColor] = Counter()
        for nx, ny in _neighbor_points(x, y, width, height):
            point = (nx, ny)
            neighbor = source_rows[ny][nx]
            if point in outline_points or point not in major_points or neighbor is None:
                continue
            if _luminance(neighbor.rgb) >= bead_luma + luma_gap:
                inward_counts[neighbor] += 1

        supported = [
            color
            for color in opposed_colors
            if inward_counts[color] >= 2
        ]
        if not supported:
            continue
        replacement = min(
            supported,
            key=lambda color: (
                -inward_counts[color],
                -_luminance(color.rgb),
                color.code,
            ),
        )
        thinned[y][x] = replacement
    return thinned


def _simplify_outline_colors(
    rows: list[list[BeadColor | None]],
    enabled: bool,
    max_luma: float,
    luma_gap: float,
) -> list[list[BeadColor | None]]:
    if not enabled or not rows:
        return rows

    height = len(rows)
    width = len(rows[0])
    outline_points: set[tuple[int, int]] = set()

    for y in range(height):
        for x in range(width):
            bead = rows[y][x]
            if bead is None:
                continue
            kind = _outline_cell_kind(rows, x, y, luma_gap)
            # Only the one-cell boundary touching blank background is an outline.
            # Internal high-contrast details (eyes, text holes, clothing lines)
            # must keep their own colors and should not be flattened globally.
            if kind != "external":
                continue
            outline_points.add((x, y))

    if not outline_points:
        return rows

    simplified = [row.copy() for row in rows]
    dark_counts: Counter[BeadColor] = Counter()
    for x, y in outline_points:
        bead = rows[y][x]
        if bead is not None and _luminance(bead.rgb) <= max_luma:
            dark_counts[bead] += 1
    if not dark_counts:
        return rows

    outline_color = min(
        dark_counts,
        key=lambda bead: (-dark_counts[bead], _luminance(bead.rgb), bead.code),
    )
    outline_luma = _luminance(outline_color.rgb)
    for x, y in outline_points:
        bead = rows[y][x]
        if bead is None:
            continue
        bead_luma = _luminance(bead.rgb)
        if bead_luma <= max_luma or bead_luma >= outline_luma + luma_gap:
            simplified[y][x] = outline_color
    return _thin_second_outline_layer(
        rows,
        simplified,
        outline_points,
        max_luma,
        luma_gap,
    )


def _limit_rows_to_top_colors(
    rows: list[list[BeadColor | None]],
    limit: int | None,
) -> list[list[BeadColor | None]]:
    if not limit or limit <= 0:
        return rows

    counts, _ = _recount_rows(rows)
    if len(counts) <= limit:
        return rows

    color_by_code: dict[str, BeadColor] = {}
    for row in rows:
        for bead in row:
            if bead is not None:
                color_by_code[bead.code] = bead

    allowed_codes = {code for code, _ in counts.most_common(limit)}
    allowed_colors = [color_by_code[code] for code in allowed_codes]
    limited = [row.copy() for row in rows]

    for y, row in enumerate(rows):
        for x, bead in enumerate(row):
            if bead is None or bead.code in allowed_codes:
                continue
            limited[y][x] = min(
                allowed_colors,
                key=lambda color: lab_distance(bead.lab, color.lab),
            )

    return limited


def _preprocess_source(
    image: Image.Image,
    pre_colors: int | None,
    mode_filter_size: int,
    denoise_method: str = "none",
    denoise_strength: int = 0,
    denoise_contrast: float = 1.0,
    denoise_sharpness: float = 1.0,
) -> Image.Image:
    image = image.convert("RGBA")
    image = _denoise_source(
        image,
        denoise_method,
        denoise_strength,
        denoise_contrast,
        denoise_sharpness,
    )
    if not pre_colors or pre_colors <= 0:
        return image

    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    quantized = rgb.quantize(colors=pre_colors, method=Image.Quantize.MEDIANCUT).convert("RGB")

    if mode_filter_size >= 3:
        if mode_filter_size % 2 == 0:
            mode_filter_size += 1
        quantized = quantized.filter(ImageFilter.ModeFilter(size=mode_filter_size))

    quantized.putalpha(alpha)
    return quantized


def _corner_background(image: Image.Image) -> tuple[int, int, int]:
    samples = [
        image.getpixel((0, 0))[:3],
        image.getpixel((image.width - 1, 0))[:3],
        image.getpixel((0, image.height - 1))[:3],
        image.getpixel((image.width - 1, image.height - 1))[:3],
    ]
    return tuple(sorted(channel)[len(channel) // 2] for channel in zip(*samples))  # type: ignore[return-value]


def _average_rgba(samples: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    total_alpha = sum(sample[3] for sample in samples)
    if total_alpha == 0:
        return 0, 0, 0, 0
    red = sum(sample[0] * sample[3] for sample in samples) / total_alpha
    green = sum(sample[1] * sample[3] for sample in samples) / total_alpha
    blue = sum(sample[2] * sample[3] for sample in samples) / total_alpha
    alpha = total_alpha / len(samples)
    return round(red), round(green), round(blue), round(alpha)


def _luminance(rgb: tuple[int, int, int]) -> float:
    return (0.299 * rgb[0]) + (0.587 * rgb[1]) + (0.114 * rgb[2])


def _is_empty_background(
    rgb: tuple[int, int, int],
    alpha: int,
    mode: str,
    background_rgb: tuple[int, int, int],
    threshold: float,
) -> bool:
    if alpha < 128:
        return True
    if mode == "none":
        return False
    if mode == "white":
        background_rgb = (255, 255, 255)
    if mode not in {"corners", "white"}:
        return False
    return lab_distance(rgb_to_lab(rgb), rgb_to_lab(background_rgb)) <= threshold


def _background_connected_mask(
    image: Image.Image,
    mode: str,
    threshold: float,
) -> list[list[bool]]:
    width, height = image.size
    mask = [[False for _ in range(width)] for _ in range(height)]
    if mode == "none":
        return mask

    background_rgb = (255, 255, 255) if mode == "white" else _corner_background(image)
    if mode not in {"corners", "white"}:
        return mask

    candidates = [[False for _ in range(width)] for _ in range(height)]
    for y in range(height):
        for x in range(width):
            r, g, b, a = image.getpixel((x, y))
            candidates[y][x] = _is_empty_background(
                (r, g, b),
                a,
                mode,
                background_rgb,
                threshold,
            )

    stack: list[tuple[int, int]] = []
    for x in range(width):
        if candidates[0][x]:
            stack.append((x, 0))
        if candidates[height - 1][x]:
            stack.append((x, height - 1))
    for y in range(height):
        if candidates[y][0]:
            stack.append((0, y))
        if candidates[y][width - 1]:
            stack.append((width - 1, y))

    while stack:
        x, y = stack.pop()
        if mask[y][x] or not candidates[y][x]:
            continue
        mask[y][x] = True
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and not mask[ny][nx]:
                stack.append((nx, ny))

    return mask


def _source_region_bounds(
    x: int,
    y: int,
    target_width: int,
    target_height: int,
    source_width: int,
    source_height: int,
) -> tuple[int, int, int, int]:
    left = int(x * source_width / target_width)
    top = int(y * source_height / target_height)
    right = int((x + 1) * source_width / target_width)
    bottom = int((y + 1) * source_height / target_height)
    return left, top, max(left + 1, right), max(top + 1, bottom)


def _quantized_source_guide(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    guide = rgba.convert("RGB").quantize(
        colors=_SOURCE_GUIDE_COLORS,
        method=Image.Quantize.MEDIANCUT,
    ).convert("RGBA")
    guide.putalpha(alpha)
    return guide


def _source_region_guides(
    source: Image.Image,
    target: tuple[int, int],
) -> list[list[_SourceRegionGuide]]:
    source = source.convert("RGBA")
    source_pixels = source.load()
    target_width, target_height = target
    raw_guides: list[list[tuple[tuple[int, int, int], float]]] = []
    global_counts: Counter[tuple[int, int, int]] = Counter()

    for y in range(target_height):
        row: list[tuple[tuple[int, int, int], float]] = []
        for x in range(target_width):
            left, top, right, bottom = _source_region_bounds(
                x,
                y,
                target_width,
                target_height,
                source.width,
                source.height,
            )
            colors: Counter[tuple[int, int, int]] = Counter()
            for sy in range(top, bottom):
                for sx in range(left, right):
                    r, g, b, a = source_pixels[sx, sy]
                    if a >= 128:
                        colors[(r, g, b)] += 1

            if not colors:
                row.append(((0, 0, 0), 0.0))
                continue
            global_counts.update(colors)
            dominant_rgb, count = colors.most_common(1)[0]
            row.append((dominant_rgb, count / colors.total()))
        raw_guides.append(row)

    global_total = global_counts.total()
    return [
        [
            _SourceRegionGuide(
                rgb,
                share,
                global_counts[rgb] / global_total if global_total else 0.0,
            )
            for rgb, share in row
        ]
        for row in raw_guides
    ]


def _should_recover_source_color(
    current_rgb: tuple[int, int, int],
    guide: _SourceRegionGuide,
) -> bool:
    if guide.share < _SOURCE_GUIDE_MIN_SHARE:
        return False
    if guide.global_share < _SOURCE_GUIDE_MIN_GLOBAL_SHARE:
        return False

    current_lab = rgb_to_lab(current_rgb)
    if current_lab.lightness < _NEAR_WHITE_MIN_LAB_L:
        return False
    if hypot(current_lab.a, current_lab.b) > _NEAR_WHITE_MAX_CHROMA:
        return False

    guide_lab = rgb_to_lab(guide.rgb)
    guide_is_dark = guide_lab.lightness <= _SOURCE_DARK_MAX_LAB_L
    guide_is_colored = hypot(guide_lab.a, guide_lab.b) >= _SOURCE_COLOR_MIN_CHROMA
    if not guide_is_dark and not guide_is_colored:
        return False
    return lab_distance(current_lab, guide_lab) >= _SOURCE_COLOR_MIN_DISTANCE


def _recover_source_region_colors(
    small: Image.Image,
    guides: list[list[_SourceRegionGuide]] | None,
    background_mask: list[list[bool]],
    enabled: bool,
) -> Image.Image:
    if not enabled or guides is None:
        return small

    recovered = small.copy()
    for y in range(small.height):
        for x in range(small.width):
            if background_mask[y][x]:
                continue
            guide = guides[y][x]
            current = small.getpixel((x, y))
            if not _should_recover_source_color(current[:3], guide):
                continue
            recovered.putpixel((x, y), (*guide.rgb, current[3]))
    return recovered


def _recover_source_region_beads(
    rows: list[list[BeadColor | None]],
    guides: list[list[_SourceRegionGuide]] | None,
    palette: Palette,
    enabled: bool,
) -> list[list[BeadColor | None]]:
    if not enabled or guides is None:
        return rows

    recovered = [row.copy() for row in rows]
    for y, row in enumerate(rows):
        for x, bead in enumerate(row):
            if bead is None:
                continue
            guide = guides[y][x]
            if not _should_recover_source_color(bead.rgb, guide):
                continue
            replacement = palette.nearest(guide.rgb)
            guide_lab = rgb_to_lab(guide.rgb)
            if lab_distance(replacement.lab, guide_lab) < lab_distance(bead.lab, guide_lab):
                recovered[y][x] = replacement
    return recovered


def _make_small_by_resize(
    image: Image.Image,
    target: tuple[int, int],
    max_colors: int | None,
) -> Image.Image:
    small = image.resize(target, Image.Resampling.LANCZOS)
    return _quantize(small, max_colors=max_colors)


def _small_photoshop_like(image: Image.Image, target: tuple[int, int]) -> Image.Image:
    return image.resize(target, Image.Resampling.LANCZOS).convert("RGBA")


def _restore_bright_details(
    source: Image.Image,
    small: Image.Image,
    background_mask: list[list[bool]],
    enabled: bool,
) -> Image.Image:
    if not enabled:
        return small

    target_width, target_height = small.size
    source_width, source_height = source.size
    margin = max(
        2,
        int(max(source_width / target_width, source_height / target_height)) + 1,
    )
    candidates: dict[tuple[int, int], tuple[tuple[int, int, int], float, float]] = {}

    def has_dark_pixel(left: int, top: int, right: int, bottom: int) -> bool:
        for sy in range(max(0, top), min(source_height, bottom)):
            for sx in range(max(0, left), min(source_width, right)):
                if _luminance(source.getpixel((sx, sy))[:3]) <= 110.0:
                    return True
        return False

    for y in range(target_height):
        for x in range(target_width):
            if background_mask[y][x]:
                continue
            if any(
                background_mask[ny][nx]
                for ny in range(max(0, y - 1), min(target_height, y + 2))
                for nx in range(max(0, x - 1), min(target_width, x + 2))
            ):
                continue

            left, top, right, bottom = _source_region_bounds(
                x,
                y,
                target_width,
                target_height,
                source_width,
                source_height,
            )
            samples = [
                source.getpixel((sx, sy))[:3]
                for sy in range(top, bottom)
                for sx in range(left, right)
            ]
            bright = [
                rgb
                for rgb in samples
                if _luminance(rgb) >= 215.0 and max(rgb) - min(rgb) <= 30
            ]
            dark = [rgb for rgb in samples if _luminance(rgb) <= 110.0]
            bright_share = len(bright) / len(samples)
            if bright_share < 0.25 or len(bright) < len(dark):
                continue

            bright_rgb = tuple(
                round(sum(rgb[channel] for rgb in bright) / len(bright))
                for channel in range(3)
            )
            small_rgb = small.getpixel((x, y))[:3]
            luma_loss = _luminance(bright_rgb) - _luminance(small_rgb)
            if luma_loss < 35.0:
                continue

            dark_on_both_sides = (
                has_dark_pixel(left - margin, top - margin, left, bottom + margin)
                and has_dark_pixel(right, top - margin, right + margin, bottom + margin)
            ) or (
                has_dark_pixel(left - margin, top - margin, right + margin, top)
                and has_dark_pixel(left - margin, bottom, right + margin, bottom + margin)
            )
            if dark_on_both_sides:
                candidates[(x, y)] = (bright_rgb, bright_share, luma_loss)

    remaining = set(candidates)
    accepted: set[tuple[int, int]] = set()
    while remaining:
        start = remaining.pop()
        component = {start}
        stack = [start]
        while stack:
            x, y = stack.pop()
            for point in _neighbor_points(x, y, target_width, target_height):
                if point in remaining:
                    remaining.remove(point)
                    component.add(point)
                    stack.append(point)

        keep_isolated_highlight = any(
            candidates[point][1] >= 0.55 and candidates[point][2] >= 60.0
            for point in component
        )
        if len(component) >= 2 or keep_isolated_highlight:
            accepted.update(component)

    restored = small.copy()
    for x, y in accepted:
        rgb = candidates[(x, y)][0]
        alpha = restored.getpixel((x, y))[3]
        restored.putpixel((x, y), (*rgb, alpha))
    return restored


def build_rgb_pattern(
    input_path: Path,
    max_size: int = 72,
    width: int | None = None,
    height: int | None = None,
    empty_background: str = "corners",
    background_threshold: float = 7.0,
    denoise_method: str = "edge",
    denoise_strength: int = 2,
    denoise_contrast: float = 1.18,
    denoise_sharpness: float = 1.35,
    bright_detail_recovery: bool = True,
    source_coverage_recovery: bool = True,
) -> Pattern:
    image = Image.open(input_path).convert("RGBA")
    image = _denoise_source(
        image,
        denoise_method,
        denoise_strength,
        denoise_contrast,
        denoise_sharpness,
    )
    target = _target_size(image, max_size=max_size, width=width, height=height)
    if target[0] > max_size or target[1] > max_size:
        raise ValueError(f"Target size {target[0]}x{target[1]} exceeds max_size={max_size}.")

    source_guides = (
        _source_region_guides(_quantized_source_guide(image), target)
        if source_coverage_recovery
        else None
    )
    small = _small_photoshop_like(image, target)
    background_mask = _background_connected_mask(small, empty_background, background_threshold)
    small = _restore_bright_details(
        image,
        small,
        background_mask,
        bright_detail_recovery,
    )
    small = _recover_source_region_colors(
        small,
        source_guides,
        background_mask,
        source_coverage_recovery,
    )
    if source_coverage_recovery:
        background_mask = _background_connected_mask(small, empty_background, background_threshold)
    rows: list[list[BeadColor | None]] = []
    counts: Counter[str] = Counter()
    colors_by_code: dict[str, BeadColor] = {}

    for y in range(small.height):
        row: list[BeadColor | None] = []
        for x in range(small.width):
            r, g, b, a = small.getpixel((x, y))
            rgb = (r, g, b)
            if background_mask[y][x]:
                row.append(None)
                continue
            code = f"RGB{r:02X}{g:02X}{b:02X}"
            bead = make_rgb_bead(code, rgb)
            row.append(bead)
            counts[bead.code] += 1
            colors_by_code[bead.code] = bead
        rows.append(row)

    return Pattern(small.width, small.height, rows, counts, colors_by_code)


def _build_by_resize(
    image: Image.Image,
    target: tuple[int, int],
    palette: Palette,
    max_colors: int | None,
    empty_background: str,
    background_threshold: float,
) -> Pattern:
    small = _make_small_by_resize(image, target, max_colors=max_colors)
    background_mask = _background_connected_mask(small, empty_background, background_threshold)

    rows: list[list[BeadColor | None]] = []
    counts: Counter[str] = Counter()
    colors_by_code: dict[str, BeadColor] = {}

    for y in range(small.height):
        row: list[BeadColor | None] = []
        for x in range(small.width):
            r, g, b, a = small.getpixel((x, y))
            rgb = (r, g, b)
            if background_mask[y][x]:
                row.append(None)
                continue
            bead = palette.nearest(rgb)
            row.append(bead)
            counts[bead.code] += 1
            colors_by_code[bead.code] = bead
        rows.append(row)

    return Pattern(small.width, small.height, rows, counts, colors_by_code)


def _build_by_region_vote(
    image: Image.Image,
    detail_image: Image.Image,
    target: tuple[int, int],
    palette: Palette,
    max_colors: int | None,
    empty_background: str,
    background_threshold: float,
    vote_threshold: float,
    min_region_pixels: int,
    palette_limit: int | None,
    local_merge_distance: float,
    local_merge_threshold: int,
    local_merge_passes: int,
    near_white_cleanup: bool,
    outline_simplify: bool,
    outline_max_luma: float,
    outline_luma_gap: float,
    detail_min_share: float,
    detail_luma_gap: float,
    detail_max_luma: float,
    detail_base_min_luma: float,
) -> Pattern:
    vote_source = _quantize(image, max_colors=max_colors)
    detail_source = detail_image.convert("RGBA")
    background_rgb = _corner_background(vote_source)
    target_width, target_height = target

    rows: list[list[BeadColor | None]] = []
    counts: Counter[str] = Counter()
    colors_by_code: dict[str, BeadColor] = {}

    for y in range(target_height):
        row: list[BeadColor | None] = []
        for x in range(target_width):
            left, top, right, bottom = _source_region_bounds(
                x,
                y,
                target_width,
                target_height,
                vote_source.width,
                vote_source.height,
            )
            samples = [
                vote_source.getpixel((sx, sy))
                for sy in range(top, bottom)
                for sx in range(left, right)
            ]
            detail_left, detail_top, detail_right, detail_bottom = _source_region_bounds(
                x,
                y,
                target_width,
                target_height,
                detail_source.width,
                detail_source.height,
            )
            detail_samples = [
                detail_source.getpixel((sx, sy))
                for sy in range(detail_top, detail_bottom)
                for sx in range(detail_left, detail_right)
            ]
            avg_r, avg_g, avg_b, avg_a = _average_rgba(samples)
            avg_rgb = (avg_r, avg_g, avg_b)
            if _is_empty_background(avg_rgb, avg_a, empty_background, background_rgb, background_threshold):
                row.append(None)
                continue

            votes: Counter[BeadColor] = Counter()
            non_empty = 0
            for r, g, b, a in samples:
                rgb = (r, g, b)
                if _is_empty_background(rgb, a, empty_background, background_rgb, background_threshold):
                    continue
                non_empty += 1
                votes[palette.nearest(rgb)] += 1

            if non_empty < min_region_pixels or not votes:
                row.append(None)
                continue

            winner, winner_count = votes.most_common(1)[0]
            avg_luma = _luminance(avg_rgb)
            if winner_count / non_empty >= vote_threshold:
                bead = winner
            else:
                bead = palette.nearest(avg_rgb)

            if detail_min_share > 0 and _luminance(bead.rgb) >= detail_base_min_luma:
                detail_votes: Counter[BeadColor] = Counter()
                for r, g, b, a in detail_samples:
                    rgb = (r, g, b)
                    if _is_empty_background(rgb, a, empty_background, background_rgb, background_threshold):
                        continue
                    if _luminance(rgb) > detail_max_luma:
                        continue
                    if avg_luma - _luminance(rgb) < detail_luma_gap:
                        continue
                    detail_votes[palette.nearest(rgb)] += 1
                if detail_votes:
                    detail_bead, detail_count = detail_votes.most_common(1)[0]
                    if detail_count / len(detail_samples) >= detail_min_share:
                        bead = detail_bead

            row.append(bead)
            counts[bead.code] += 1
            colors_by_code[bead.code] = bead
        rows.append(row)

    rows = _limit_rows_to_top_colors(rows, palette_limit)
    rows = _local_merge_similar_colors(
        rows,
        local_merge_distance,
        local_merge_threshold,
        local_merge_passes,
    )
    rows = _merge_small_near_white_components(rows, near_white_cleanup)
    rows = _simplify_outline_colors(
        rows,
        outline_simplify,
        outline_max_luma,
        outline_luma_gap,
    )
    counts, colors_by_code = _recount_rows(rows)

    return Pattern(target_width, target_height, rows, counts, colors_by_code)


def _build_by_global_resize(
    image: Image.Image,
    detail_image: Image.Image,
    source_guides: list[list[_SourceRegionGuide]] | None,
    target: tuple[int, int],
    palette: Palette,
    palette_limit: int | None,
    empty_background: str,
    background_threshold: float,
    global_color_merge_distance: float,
    dominant_snap_distance: float,
    dominant_snap_penalty: float,
    local_merge_distance: float,
    local_merge_threshold: int,
    local_merge_passes: int,
    near_white_cleanup: bool,
    outline_simplify: bool,
    outline_max_luma: float,
    outline_luma_gap: float,
    bright_detail_recovery: bool,
    source_coverage_recovery: bool,
) -> Pattern:
    small = image.resize(target, Image.Resampling.LANCZOS).convert("RGBA")
    background_mask = _background_connected_mask(small, empty_background, background_threshold)
    small = _restore_bright_details(
        detail_image,
        small,
        background_mask,
        bright_detail_recovery,
    )
    small = _recover_source_region_colors(
        small,
        source_guides,
        background_mask,
        source_coverage_recovery,
    )
    if source_coverage_recovery:
        background_mask = _background_connected_mask(small, empty_background, background_threshold)
    working_palette = _limited_palette_for_image(
        small,
        palette,
        palette_limit,
        empty_background,
        background_threshold,
    )
    rgb_counts: Counter[tuple[int, int, int]] = Counter()
    for y in range(small.height):
        for x in range(small.width):
            if not background_mask[y][x]:
                rgb_counts[small.getpixel((x, y))[:3]] += 1

    dominant_counts: Counter[BeadColor] = Counter()
    for y in range(small.height):
        for x in range(small.width):
            if background_mask[y][x]:
                continue
            rgb = small.getpixel((x, y))[:3]
            dominant_counts[working_palette.nearest(rgb)] += 1

    dominant_colors = [color for color, _ in dominant_counts.most_common()]
    rgb_beads: dict[tuple[int, int, int], BeadColor] = {}
    for rgb in rgb_counts:
        bead = working_palette.nearest(rgb)
        if dominant_snap_distance > 0:
            pixel_lab = rgb_to_lab(rgb)
            nearest_distance = lab_distance(pixel_lab, bead.lab)
            for dominant in dominant_colors:
                dominant_distance = lab_distance(pixel_lab, dominant.lab)
                if (
                    dominant_distance <= dominant_snap_distance
                    and dominant_distance <= nearest_distance + dominant_snap_penalty
                ):
                    bead = dominant
                    break
        rgb_beads[rgb] = bead

    provisional_counts: Counter[BeadColor] = Counter()
    for rgb, count in rgb_counts.items():
        provisional_counts[rgb_beads[rgb]] += count

    rgb_groups = _group_similar_rgb_colors(rgb_counts, global_color_merge_distance)
    group_votes: dict[tuple[int, int, int], Counter[BeadColor]] = {}
    for rgb, count in rgb_counts.items():
        group_rgb = rgb_groups[rgb]
        group_votes.setdefault(group_rgb, Counter())[rgb_beads[rgb]] += count

    group_beads: dict[tuple[int, int, int], BeadColor] = {}
    for group_rgb, votes in group_votes.items():
        group_beads[group_rgb] = _choose_global_group_bead(
            group_rgb,
            votes,
            provisional_counts,
        )

    rows: list[list[BeadColor | None]] = []
    counts: Counter[str] = Counter()
    colors_by_code: dict[str, BeadColor] = {}

    for y in range(small.height):
        row: list[BeadColor | None] = []
        for x in range(small.width):
            r, g, b, a = small.getpixel((x, y))
            rgb = (r, g, b)
            if background_mask[y][x]:
                row.append(None)
                continue
            bead = group_beads[rgb_groups[rgb]]
            row.append(bead)
            counts[bead.code] += 1
            colors_by_code[bead.code] = bead
        rows.append(row)

    rows = _local_merge_similar_colors(
        rows,
        local_merge_distance,
        local_merge_threshold,
        local_merge_passes,
    )
    rows = _merge_small_near_white_components(rows, near_white_cleanup)
    rows = _simplify_outline_colors(
        rows,
        outline_simplify,
        outline_max_luma,
        outline_luma_gap,
    )
    rows = _recover_source_region_beads(
        rows,
        source_guides,
        working_palette,
        source_coverage_recovery,
    )
    counts, colors_by_code = _recount_rows(rows)

    return Pattern(small.width, small.height, rows, counts, colors_by_code)


def _limited_palette_for_image(
    image: Image.Image,
    palette: Palette,
    palette_limit: int | None,
    empty_background: str,
    background_threshold: float,
) -> Palette:
    if not palette_limit or palette_limit <= 0 or palette_limit >= len(palette.colors):
        return palette

    scan = image.copy()
    scan.thumbnail((160, 160), Image.Resampling.BOX)
    background_mask = _background_connected_mask(scan, empty_background, background_threshold)
    counts: Counter[BeadColor] = Counter()

    scan_data = scan.get_flattened_data() if hasattr(scan, "get_flattened_data") else scan.getdata()
    for index, (r, g, b, a) in enumerate(scan_data):
        x = index % scan.width
        y = index // scan.width
        if background_mask[y][x]:
            continue
        rgb = (r, g, b)
        counts[palette.nearest(rgb)] += 1

    if not counts:
        return palette
    selected = [color for color, _ in counts.most_common(palette_limit)]
    return palette.subset(selected)


def build_pattern(
    input_path: Path,
    palette: Palette,
    max_size: int = 72,
    width: int | None = None,
    height: int | None = None,
    max_colors: int | None = 0,
    pre_colors: int | None = 12,
    pre_mode_filter_size: int = 0,
    denoise_method: str = "edge",
    denoise_strength: int = 2,
    denoise_contrast: float = 1.18,
    denoise_sharpness: float = 1.35,
    empty_background: str = "corners",
    background_threshold: float = 7.0,
    pixel_method: str = "global",
    vote_threshold: float = 0.35,
    min_region_pixels: int = 1,
    palette_limit: int | None = 0,
    global_color_merge_distance: float = 6.0,
    dominant_snap_distance: float = 14.0,
    dominant_snap_penalty: float = 3.0,
    local_merge_distance: float = 14.0,
    local_merge_threshold: int = 2,
    local_merge_passes: int = 1,
    near_white_cleanup: bool = True,
    outline_simplify: bool = True,
    outline_max_luma: float = 135.0,
    outline_luma_gap: float = 26.0,
    bright_detail_recovery: bool = True,
    source_coverage_recovery: bool = True,
    detail_min_share: float = 0.0,
    detail_luma_gap: float = 38.0,
    detail_max_luma: float = 105.0,
    detail_base_min_luma: float = 205.0,
) -> Pattern:
    image = Image.open(input_path).convert("RGBA")
    detail_image = _denoise_source(
        image,
        denoise_method,
        denoise_strength,
        denoise_contrast,
        denoise_sharpness,
    )
    image = _preprocess_source(
        image,
        pre_colors,
        pre_mode_filter_size,
        denoise_method,
        denoise_strength,
        denoise_contrast,
        denoise_sharpness,
    )
    target = _target_size(image, max_size=max_size, width=width, height=height)
    if target[0] > max_size or target[1] > max_size:
        raise ValueError(f"Target size {target[0]}x{target[1]} exceeds max_size={max_size}.")

    if pixel_method == "global":
        source_guides = (
            _source_region_guides(_quantized_source_guide(detail_image), target)
            if source_coverage_recovery
            else None
        )
        return _build_by_global_resize(
            image=image,
            detail_image=detail_image,
            source_guides=source_guides,
            target=target,
            palette=palette,
            palette_limit=palette_limit,
            empty_background=empty_background,
            background_threshold=background_threshold,
            global_color_merge_distance=global_color_merge_distance,
            dominant_snap_distance=dominant_snap_distance,
            dominant_snap_penalty=dominant_snap_penalty,
            local_merge_distance=local_merge_distance,
            local_merge_threshold=local_merge_threshold,
            local_merge_passes=local_merge_passes,
            near_white_cleanup=near_white_cleanup,
            outline_simplify=outline_simplify,
            outline_max_luma=outline_max_luma,
            outline_luma_gap=outline_luma_gap,
            bright_detail_recovery=bright_detail_recovery,
            source_coverage_recovery=source_coverage_recovery,
        )

    if pixel_method == "resize":
        working_palette = _limited_palette_for_image(
            image,
            palette,
            palette_limit,
            empty_background,
            background_threshold,
        )
        return _build_by_resize(
            image=image,
            target=target,
            palette=working_palette,
            max_colors=max_colors,
            empty_background=empty_background,
            background_threshold=background_threshold,
        )
    if pixel_method == "vote":
        return _build_by_region_vote(
            image=image,
            detail_image=detail_image,
            target=target,
            palette=palette,
            max_colors=max_colors,
            empty_background=empty_background,
            background_threshold=background_threshold,
            vote_threshold=vote_threshold,
            min_region_pixels=min_region_pixels,
            palette_limit=palette_limit,
            local_merge_distance=local_merge_distance,
            local_merge_threshold=local_merge_threshold,
            local_merge_passes=local_merge_passes,
            near_white_cleanup=near_white_cleanup,
            outline_simplify=outline_simplify,
            outline_max_luma=outline_max_luma,
            outline_luma_gap=outline_luma_gap,
            detail_min_share=detail_min_share,
            detail_luma_gap=detail_luma_gap,
            detail_max_luma=detail_max_luma,
            detail_base_min_luma=detail_base_min_luma,
        )
    raise ValueError(f"Unsupported pixel_method: {pixel_method}")
