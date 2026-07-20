from __future__ import annotations

from dataclasses import dataclass
from math import pow


@dataclass(frozen=True)
class LabColor:
    lightness: float
    a: float
    b: float


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid hex color: {value!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_lab(rgb: tuple[int, int, int]) -> LabColor:
    r, g, b = [channel / 255.0 for channel in rgb]

    def pivot_rgb(value: float) -> float:
        if value > 0.04045:
            return pow((value + 0.055) / 1.055, 2.4)
        return value / 12.92

    r, g, b = pivot_rgb(r), pivot_rgb(g), pivot_rgb(b)

    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.00000
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def pivot_xyz(value: float) -> float:
        if value > 0.008856:
            return pow(value, 1 / 3)
        return (7.787 * value) + (16 / 116)

    x, y, z = pivot_xyz(x), pivot_xyz(y), pivot_xyz(z)
    return LabColor((116 * y) - 16, 500 * (x - y), 200 * (y - z))


def lab_distance(left: LabColor, right: LabColor) -> float:
    return (
        (left.lightness - right.lightness) ** 2
        + (left.a - right.a) ** 2
        + (left.b - right.b) ** 2
    ) ** 0.5
