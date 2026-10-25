import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import utils
from svg_wheel import generate_svg_wheel


def wheel(abi):
    return {
        "packagetype": "bdist_wheel",
        "filename": f"example-1.0-cp315-{abi}-manylinux_2_17_x86_64.whl",
    }


class PackageSelectionTests(unittest.TestCase):
    def test_abi_tags_only_from_wheel_abi_fields(self):
        files = [
            wheel("abi3"),
            wheel("abi3t"),
            wheel("abi3.abi3t"),
            wheel("cp315t"),
            wheel("none"),
            {"packagetype": "sdist", "filename": "example-abi3.tar.gz"},
        ]
        self.assertEqual(utils.stable_abi_tags(files), {"abi3", "abi3t"})
        self.assertEqual(utils.stable_abi_tags([wheel("cp315t")]), set())

    def test_top_100_selected_after_filtering_in_download_order(self):
        packages = [{"name": f"package-{i}", "downloads": 500 - i} for i in range(120)]
        tags = {
            package["name"]: ({"abi3", "abi3t"} if i % 2 else {"abi3"})
            for i, package in enumerate(packages)
            if i >= 5
        }
        with patch.object(
            utils,
            "get_package_abi_tags",
            side_effect=lambda name: tags.get(name, set()),
        ):
            result = utils.annotate_wheels(list(reversed(packages)), 100)
        self.assertEqual(len(result), 100)
        self.assertEqual(
            [p["name"] for p in result],
            [f"package-{i}" for i in range(5, 105)],
        )
        for item in result:
            expected = "abi3t" if int(item["name"].split("-")[-1]) % 2 else "abi3-only"
            self.assertEqual(item["css_class"], expected)
            self.assertEqual(item["has_abi3t_wheel"], expected == "abi3t")

    def test_abi3t_without_abi3_is_not_included(self):
        with patch.object(
            utils,
            "get_package_abi_tags",
            side_effect=lambda name: {"abi3t"} if name == "first" else {"abi3"},
        ):
            result = utils.annotate_wheels(
                [
                    {"name": "first", "downloads": 2},
                    {"name": "second", "downloads": 1},
                ],
                1,
            )
        self.assertEqual([p["name"] for p in result], ["second"])

    def test_pypi_non_success_is_not_treated_as_unqualified(self):
        class Response:
            status_code = 503

            def raise_for_status(self):
                raise RuntimeError("PyPI unavailable")

        with patch.object(utils, "_session") as session:
            session.return_value.get.return_value = Response()
            with self.assertRaisesRegex(RuntimeError, "PyPI unavailable"):
                utils.get_package_abi_tags("example")

    def test_deprecated_project_is_skipped(self):
        with patch.object(
            utils, "get_package_abi_tags", return_value={"abi3"}
        ) as getter:
            result = utils.annotate_wheels(
                [
                    {"name": "BeautifulSoup", "downloads": 2},
                    {"name": "good", "downloads": 1},
                ],
                1,
            )
        self.assertEqual(result[0]["name"], "good")
        getter.assert_called_once_with("good")

    def test_get_top_packages_sorts_by_download_count(self):
        content = json.dumps(
            {
                "rows": [
                    {"project": "lower", "download_count": 10},
                    {"project": "higher", "download_count": 20},
                ]
            }
        )
        with patch("builtins.open", return_value=io.StringIO(content)):
            result = utils.get_top_packages()
        self.assertEqual([p["name"] for p in result], ["higher", "lower"])

    def test_svg_fraction_uses_selected_count(self):
        packages = [
            {
                "name": "one",
                "css_class": "abi3t",
                "icon": "🧵",
                "stable_free_threaded_wheel": True,
            },
            {
                "name": "two",
                "css_class": "abi3-only",
                "icon": "✗",
                "stable_free_threaded_wheel": False,
            },
        ]
        with tempfile.TemporaryDirectory() as temp:
            with patch(
                "svg_wheel.open",
                side_effect=lambda *args, **kwargs: open(
                    Path(temp) / args[0], *args[1:], **kwargs
                ),
                create=True,
            ):
                generate_svg_wheel(packages, len(packages))
            root = ET.parse(Path(temp) / "wheel.svg").getroot()
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertEqual(
            [element.attrib["class"] for element in root.findall("s:path", ns)],
            ["abi3t", "abi3-only"],
        )
        self.assertEqual(
            [element.text for element in root.findall("s:text", ns)], ["1", "2"]
        )


if __name__ == "__main__":
    unittest.main()
