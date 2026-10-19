import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_datasets as build  # noqa: E402


class DatasetBuilderTests(unittest.TestCase):
    def test_parse_blocks(self):
        blocks = build.parse_blocks(
            "# sample\n0000..007F; Basic Latin\n0080..00FF; Latin-1 Supplement\n"
        )
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["start"], 0)
        self.assertEqual(blocks[1]["end"], 0xFF)

    def test_parse_script_aliases(self):
        names, codes = build.parse_script_aliases(
            "sc ; Latn ; Latin\nsc ; Zyyy ; Common\n"
        )
        self.assertEqual(names["Latin"], "Latn")
        self.assertEqual(codes["Zyyy"], "Common")

    def test_script_membership_prefers_real_script_over_common(self):
        names = {"Latin": "Latn", "Common": "Zyyy"}
        dominant, codes = build.script_codes_for_block(
            0x20,
            0x7E,
            [(0x20, 0x40, "Common"), (0x41, 0x5A, "Latin"), (0x5B, 0x7E, "Common")],
            [],
            names,
        )
        self.assertEqual(dominant, "Latn")
        self.assertEqual(codes, ["Latn"])

    def test_unicode_data_algorithmic_ranges_are_expanded(self):
        sample = (
            "0041;LATIN CAPITAL LETTER A;Lu;0;L;;;;;N;;;;0061;\n"
            "3400;<CJK Ideograph, First>;Lo;0;L;;;;;N;;;;;\n"
            "3402;<CJK Ideograph, Last>;Lo;0;L;;;;;N;;;;;\n"
        )
        entries = build.parse_unicode_data(sample)
        self.assertEqual(entries[0x41], ("Lu", "LATIN CAPITAL LETTER A"))
        self.assertEqual(entries[0x3401], ("Lo", "CJK Ideograph-3401"))

    def test_public_script_label_normalization(self):
        self.assertEqual(build.normalize_script_label("Javanese script"), "javanese")
        self.assertEqual(build.normalize_script_label("Kawi writing system"), "kawi")

    def test_wikidata_queries_cover_multiple_country_language_sources(self):
        query_p2936 = build.wikidata_query("P2936")
        query_p37 = build.wikidata_query("P37")
        query_p17 = build.wikidata_query("P17-language-country")
        self.assertIn("wdt:P2936", query_p2936)
        self.assertIn("wdt:P37", query_p37)
        self.assertIn("wdt:P17", query_p17)
        for query in (query_p2936, query_p37, query_p17):
            self.assertIn("wdt:P282", query)
            self.assertIn("wdt:P506", query)
            self.assertIn("LIMIT 10000", query)

    def test_practice_index_separates_letters_from_other_printables(self):
        definitions = {
            "basic_latin": {"range": "0020-0042"},
        }
        character_data = {
            0x20: ("Zs", "SPACE"),
            0x21: ("Po", "EXCLAMATION MARK"),
            0x31: ("Nd", "DIGIT ONE"),
            0x41: ("Lu", "LATIN CAPITAL LETTER A"),
            0x42: ("Lu", "LATIN CAPITAL LETTER B"),
        }
        index = build.build_practice_character_index(definitions, character_data, "18.0.0")
        self.assertEqual(index["blocks"]["basic_latin"]["letters"], [0x41, 0x42])
        self.assertEqual(index["blocks"]["basic_latin"]["other_printable"], [0x21, 0x31])
        self.assertEqual(index["metadata"]["unicode_version"], "18.0.0")

    def test_country_mapping_uses_sourced_script_code(self):
        definitions = {
            "basic_latin": {"script_codes": ["Latn"]},
            "general_punctuation": {"script_codes": ["Zyyy"]},
        }
        relations = [{
            "country_iso2": "US",
            "country_iso3": "USA",
            "country_label_en": "United States",
            "language_id": "Q1860",
            "language_label_en": "English",
            "language_iso639_3": "eng",
            "script_id": "Q8229",
            "script_label_en": "Latin script",
            "script_code": "Latn",
            "country_source_property": "P297",
            "language_source_property": "P2936",
            "writing_system_source_property": "P282",
            "script_code_source_property": "P506",
            "source": "Wikidata",
            "source_url": "https://www.wikidata.org/wiki/Q1860",
        }]
        countries, languages, output = build.build_public_datasets(
            definitions, relations, "18.0.0"
        )
        self.assertEqual(countries, {"US": ["basic_latin"]})
        self.assertEqual(languages[0]["iso639_3"], "eng")
        self.assertEqual(output["stats"]["matched_relationship_count"], 1)


if __name__ == "__main__":
    unittest.main()
