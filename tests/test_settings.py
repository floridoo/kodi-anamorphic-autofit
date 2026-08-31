import os
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SETTINGS_PATH = os.path.join(ROOT, "service.anamorphic.autofit", "resources", "settings.xml")
STRINGS_PATH = os.path.join(
    ROOT,
    "service.anamorphic.autofit",
    "resources",
    "language",
    "resource.language.en_gb",
    "strings.po",
)


class SettingsTests(unittest.TestCase):
    def test_settings_labels_resolve_to_english_strings(self):
        settings_root = ET.parse(SETTINGS_PATH).getroot()
        with open(STRINGS_PATH, encoding="utf-8") as strings_file:
            strings_text = strings_file.read()
        string_ids = set(re.findall(r'^msgctxt "#(\d+)"$', strings_text, flags=re.MULTILINE))

        references = []
        for element in settings_root.iter():
            for attribute in ("label", "help"):
                value = element.get(attribute)
                if value:
                    references.append(value)
            if element.tag == "heading" and element.text:
                references.append(element.text.strip())

        self.assertTrue(references)
        for reference in references:
            self.assertRegex(reference, r"^\d+$")
            self.assertIn(reference, string_ids)


if __name__ == "__main__":
    unittest.main()
