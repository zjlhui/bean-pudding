from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .color import LabColor, lab_distance, rgb_to_lab


@dataclass(frozen=True)
class BeadColor:
    code: str
    name: str
    hex: str
    rgb: tuple[int, int, int]
    brand: str

    @cached_property
    def lab(self) -> LabColor:
        return rgb_to_lab(self.rgb)


class Palette:
    def __init__(self, colors: list[BeadColor]) -> None:
        if not colors:
            raise ValueError("Palette must contain at least one color.")
        self.colors = colors

    @classmethod
    def from_csv(cls, path: Path) -> "Palette":
        colors: list[BeadColor] = []
        with path.open("r", encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                colors.append(
                    BeadColor(
                        code=row["code"],
                        name=row["name"],
                        hex=row["hex"],
                        rgb=(int(row["r"]), int(row["g"]), int(row["b"])),
                        brand=row.get("brand", ""),
                    )
                )
        return cls(colors)

    def nearest(self, rgb: tuple[int, int, int]) -> BeadColor:
        lab = rgb_to_lab(rgb)
        return min(self.colors, key=lambda color: lab_distance(lab, color.lab))

    def subset(self, colors: list[BeadColor]) -> "Palette":
        return Palette(colors)

    def without_codes(self, codes: set[str]) -> "Palette":
        if not codes:
            return self
        colors = [color for color in self.colors if color.code not in codes]
        return Palette(colors)
