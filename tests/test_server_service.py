from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from server.service import GenerationOptions, generate_pattern_files, validate_options


class ServerServiceTests(unittest.TestCase):
    def test_mini_program_size_options_are_valid(self) -> None:
        for max_size in (29, 52, 78):
            validate_options(GenerationOptions(max_size=max_size))

    def test_invalid_options_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "16 到 78"):
            validate_options(GenerationOptions(max_size=79))
        with self.assertRaisesRegex(ValueError, "0 到 64"):
            validate_options(GenerationOptions(color_limit=-1))

    def test_generation_creates_both_charts_and_summary(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            input_path = output_dir / "input.png"
            source = Image.new("RGB", (64, 64), "white")
            source.paste((224, 160, 140), (8, 8, 56, 56))
            source.paste((80, 45, 35), (8, 8, 56, 11))
            source.save(input_path)

            result = generate_pattern_files(
                input_path,
                output_dir,
                GenerationOptions(max_size=29, color_limit=10),
            )

            self.assertEqual((result.width, result.height), (29, 29))
            self.assertGreater(result.bead_count, 0)
            self.assertEqual(result.color_count, len(result.summary))
            self.assertEqual(sum(item["count"] for item in result.summary), result.bead_count)
            self.assertTrue(result.summary_path.is_file())
            self.assertFalse((output_dir / "source.png").exists())

            for image_path in (result.pattern_path, result.rgb_path):
                with Image.open(image_path) as image:
                    self.assertEqual(image.format, "JPEG")
                    self.assertGreater(image.width, 0)
                    self.assertGreater(image.height, 0)


if __name__ == "__main__":
    unittest.main()
