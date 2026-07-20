from __future__ import annotations

from collections import Counter
import unittest

from PIL import Image

from bean_pudding.generator import (
    _SourceRegionGuide,
    _choose_global_group_bead,
    _group_similar_rgb_colors,
    _recover_source_region_beads,
    _recover_source_region_colors,
    _source_region_guides,
)
from bean_pudding.palette import BeadColor, Palette


def _bead(code: str, rgb: tuple[int, int, int]) -> BeadColor:
    return BeadColor(code, code, "#000000", rgb, "test")


class SourceCoverageRecoveryTests(unittest.TestCase):
    def test_global_rgb_group_uses_the_common_color_as_anchor(self) -> None:
        common = (100, 100, 100)
        similar = (104, 102, 100)
        different = (220, 220, 220)

        groups = _group_similar_rgb_colors(
            Counter({common: 20, similar: 2, different: 1}),
            3.0,
        )

        self.assertEqual(groups[common], common)
        self.assertEqual(groups[similar], common)
        self.assertEqual(groups[different], different)

    def test_zero_global_rgb_distance_disables_grouping(self) -> None:
        colors = Counter({(100, 100, 100): 20, (101, 101, 101): 2})

        groups = _group_similar_rgb_colors(colors, 0.0)

        self.assertEqual(groups, {rgb: rgb for rgb in colors})

    def test_global_group_prefers_a_common_candidate_with_enough_votes(self) -> None:
        white = _bead("H1", (255, 255, 255))
        transition = _bead("H19", (242, 238, 229))

        selected = _choose_global_group_bead(
            (247, 239, 234),
            Counter({transition: 75, white: 60}),
            Counter({white: 1350, transition: 237}),
        )

        self.assertEqual(selected, white)

    def test_region_guide_uses_the_full_source_area(self) -> None:
        source = Image.new("RGBA", (4, 2), (255, 255, 255, 255))
        pink = (247, 227, 236, 255)
        for index in range(5):
            source.putpixel((index % 4, index // 4), pink)

        guide = _source_region_guides(source, (1, 1))[0][0]

        self.assertEqual(guide.rgb, pink[:3])
        self.assertAlmostEqual(guide.share, 5 / 8)
        self.assertAlmostEqual(guide.global_share, 5 / 8)

    def test_confident_pink_majority_recovers_a_white_rgb_cell(self) -> None:
        small = Image.new("RGBA", (1, 1), (255, 255, 255, 255))
        guides = [[_SourceRegionGuide((247, 227, 236), 0.60, 0.10)]]

        recovered = _recover_source_region_colors(small, guides, [[False]], True)

        self.assertEqual(recovered.getpixel((0, 0))[:3], (247, 227, 236))

    def test_rare_transition_color_does_not_replace_white(self) -> None:
        small = Image.new("RGBA", (1, 1), (255, 255, 255, 255))
        guides = [[_SourceRegionGuide((243, 220, 195), 0.90, 0.01)]]

        recovered = _recover_source_region_colors(small, guides, [[False]], True)

        self.assertEqual(recovered.getpixel((0, 0))[:3], (255, 255, 255))

    def test_background_cell_is_not_recovered(self) -> None:
        small = Image.new("RGBA", (1, 1), (255, 255, 255, 255))
        guides = [[_SourceRegionGuide((247, 227, 236), 0.60, 0.10)]]

        recovered = _recover_source_region_colors(small, guides, [[True]], True)

        self.assertEqual(recovered.getpixel((0, 0))[:3], (255, 255, 255))

    def test_white_bead_recovers_to_nearest_allowed_pink(self) -> None:
        white = _bead("H1", (255, 255, 255))
        pink = _bead("E17", (247, 227, 236))
        palette = Palette([white, pink])
        guides = [[_SourceRegionGuide((252, 232, 236), 0.75, 0.10)]]

        recovered = _recover_source_region_beads([[white]], guides, palette, True)

        self.assertEqual(recovered[0][0], pink)


if __name__ == "__main__":
    unittest.main()
