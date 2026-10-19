#!/usr/bin/env python3
"""Generate World Script Explorer datasets from public Unicode and Wikidata sources.

No third-party Python packages are required.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_URL = "https://github.com/AnggaConni/Script-Explorer"
UNICODE_LATEST_BASE = "https://www.unicode.org/Public/UCD/latest/ucd"
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "WorldScriptExplorerDataPipeline/1.0 (public dataset build; " + REPO_URL + ")"
UCD_FILES = (
    "Blocks.txt",
    "Scripts.txt",
    "ScriptExtensions.txt",
    "UnicodeData.txt",
    "PropertyValueAliases.txt",
)
GENERIC_SCRIPT_CODES = {"Zyyy", "Zinh", "Zzzz"}
GENERIC_SCRIPT_NAMES = {"Common", "Inherited", "Unknown"}
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_text(url: str, *, headers: dict[str, str] | None = None, timeout: int = 120) -> tuple[str, str]:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain, application/json;q=0.9, */*;q=0.8",
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8-sig")
                return payload, response.geturl()
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_HTTP_CODES or attempt == 2:
                raise RuntimeError(f"HTTP {exc.code} while downloading {url}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 2:
                raise RuntimeError(f"Could not download {url}: {exc}") from exc
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not download {url}: {last_error}")


def resolve_unicode_version(requested: str) -> tuple[str, str]:
    requested = requested.strip().lower()
    if requested != "latest":
        if not re.fullmatch(r"\d+\.\d+\.\d+", requested):
            raise ValueError("Unicode version must be 'latest' or an exact version such as 18.0.0.")
        return requested, f"https://www.unicode.org/Public/{requested}/ucd"

    readme, final_url = fetch_text(f"{UNICODE_LATEST_BASE}/ReadMe.txt")
    path_match = re.search(r"/Public/(\d+\.\d+\.\d+)/ucd/", final_url)
    if path_match:
        return path_match.group(1), f"https://www.unicode.org/Public/{path_match.group(1)}/ucd"

    candidates = (
        r"Unicode Character Database[^\n]{0,100}?Version\s+(\d+\.\d+\.\d+)",
        r"\bVersion\s+(\d+\.\d+\.\d+)\b",
        r"\bUCD\s+(\d+\.\d+\.\d+)\b",
    )
    for pattern in candidates:
        match = re.search(pattern, readme, re.IGNORECASE)
        if match:
            version = match.group(1)
            return version, f"https://www.unicode.org/Public/{version}/ucd"
    raise RuntimeError(
        "Could not resolve the latest stable Unicode UCD version from the official ReadMe URL "
        f"(resolved URL: {final_url}). No data files were changed."
    )


def download_ucd(version: str, base_url: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    contents: dict[str, str] = {}
    sources: dict[str, dict[str, str]] = {}
    for filename in UCD_FILES:
        url = f"{base_url}/{filename}"
        content, final_url = fetch_text(url)
        contents[filename] = content
        sources[filename] = {
            "url": final_url,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
    return contents, sources


def parse_blocks(text: str) -> list[dict[str, int | str]]:
    blocks: list[dict[str, int | str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            code_range, name = [part.strip() for part in line.split(";", 1)]
            if ".." in code_range:
                first_text, last_text = code_range.split("..", 1)
            else:
                first_text = last_text = code_range
            first, last = int(first_text, 16), int(last_text, 16)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid Blocks.txt line: {raw_line}") from exc
        if first > last or (blocks and first <= int(blocks[-1]["end"])):
            raise ValueError(f"Overlapping or invalid Unicode block range: {raw_line}")
        blocks.append({"start": first, "end": last, "name": name})
    if not blocks:
        raise ValueError("Unicode Blocks.txt parsed to zero blocks.")
    return blocks


def parse_script_aliases(text: str) -> tuple[dict[str, str], dict[str, str]]:
    name_to_code: dict[str, str] = {}
    code_to_name: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 3 or parts[0] != "sc":
            continue
        code = parts[1]
        canonical_name = parts[-1]
        code_to_name[code] = canonical_name
        for alias in parts[2:]:
            if alias:
                name_to_code[alias] = code
    if not code_to_name:
        raise ValueError("Could not parse script aliases from PropertyValueAliases.txt.")
    return name_to_code, code_to_name


def parse_range_property(text: str, *, value_is_codes: bool = False) -> list[tuple[int, int, str]]:
    parsed: list[tuple[int, int, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 2:
            continue
        cp_range, value = parts[0], parts[1]
        if ".." in cp_range:
            left, right = cp_range.split("..", 1)
        else:
            left = right = cp_range
        try:
            first, last = int(left, 16), int(right, 16)
        except ValueError as exc:
            raise ValueError(f"Invalid Unicode property range: {raw_line}") from exc
        parsed.append((first, last, value if value_is_codes else value))
    parsed.sort(key=lambda item: item[0])
    return parsed


def overlaps(block_start: int, block_end: int, rows: list[tuple[int, int, str]]):
    for first, last, value in rows:
        if last < block_start:
            continue
        if first > block_end:
            break
        yield max(first, block_start), min(last, block_end), value


def script_codes_for_block(
    start: int,
    end: int,
    script_ranges: list[tuple[int, int, str]],
    extension_ranges: list[tuple[int, int, str]],
    name_to_code: dict[str, str],
) -> tuple[str, list[str]]:
    primary_counts: collections.Counter[str] = collections.Counter()
    all_counts: collections.Counter[str] = collections.Counter()
    for first, last, script_name in overlaps(start, end, script_ranges):
        code = name_to_code.get(script_name)
        if not code:
            continue
        size = last - first + 1
        all_counts[code] += size
        if code not in GENERIC_SCRIPT_CODES and script_name not in GENERIC_SCRIPT_NAMES:
            primary_counts[code] += size

    extension_codes: set[str] = set()
    for _first, _last, values in overlaps(start, end, extension_ranges):
        extension_codes.update(
            code for code in values.split()
            if code and code not in GENERIC_SCRIPT_CODES
        )

    codes = sorted(set(primary_counts) | extension_codes)
    if primary_counts:
        dominant = sorted(primary_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    elif codes:
        dominant = codes[0]
    elif all_counts:
        dominant = sorted(all_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    else:
        dominant = "Zzzz"
    if not codes and dominant in GENERIC_SCRIPT_CODES:
        codes = [dominant]
    return dominant, codes


def parse_unicode_data(text: str) -> dict[int, tuple[str, str]]:
    """Return codepoint -> (general category, character name).

    UnicodeData uses First/Last records for algorithmically named ranges. Expand
    those ranges so samples can be selected without guessing unassigned codepoints.
    """
    result: dict[int, tuple[str, str]] = {}
    pending: tuple[int, str, str] | None = None

    for raw_line in text.splitlines():
        fields = raw_line.split(";")
        if len(fields) < 3:
            continue
        try:
            codepoint = int(fields[0], 16)
        except ValueError:
            continue
        name = fields[1]
        category = fields[2]

        first_match = re.fullmatch(r"<(.+), First>", name)
        last_match = re.fullmatch(r"<(.+), Last>", name)
        if first_match:
            pending = (codepoint, category, first_match.group(1))
            continue
        if last_match and pending:
            range_start, range_category, range_name = pending
            if range_category == category and codepoint >= range_start:
                for cp in range(range_start, codepoint + 1):
                    result[cp] = (category, f"{range_name}-{cp:04X}")
            pending = None
            continue
        result[codepoint] = (category, name)

    if not result:
        raise ValueError("UnicodeData.txt parsed to zero character entries.")
    return result


def pick_sample(start: int, end: int, character_data: dict[int, tuple[str, str]]) -> tuple[str, str, int | None]:
    fallback: tuple[str, str, int] | None = None
    for cp in range(start, end + 1):
        entry = character_data.get(cp)
        if not entry:
            continue
        category, name = entry
        if category.startswith("L"):
            return chr(cp), name, cp
        if fallback is None and category[0] in {"M", "N", "P", "S"}:
            fallback = (chr(cp), name, cp)
    if fallback:
        return fallback
    return "", "", None


def slugify(name: str, existing: set[str], start: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "unicode_block"
    if slug in existing:
        slug = f"{slug}_{start:04x}"
    existing.add(slug)
    return slug


def font_family_for_script(code: str, script_name: str) -> str:
    if code in GENERIC_SCRIPT_CODES or code in {"Zsym", "Zsye", "Zxxx"}:
        return "Noto+Sans"
    return "Noto+Sans+" + re.sub(r"\s+", "+", script_name.strip())


def build_definitions(
    blocks: list[dict[str, int | str]],
    script_ranges: list[tuple[int, int, str]],
    extension_ranges: list[tuple[int, int, str]],
    name_to_code: dict[str, str],
    code_to_name: dict[str, str],
    character_data: dict[int, tuple[str, str]],
) -> dict[str, dict[str, object]]:
    definitions: dict[str, dict[str, object]] = {}
    existing_slugs: set[str] = set()
    for block in blocks:
        start, end, name = int(block["start"]), int(block["end"]), str(block["name"])
        dominant, codes = script_codes_for_block(
            start, end, script_ranges, extension_ranges, name_to_code
        )
        sample, sample_name, sample_cp = pick_sample(start, end, character_data)
        primary_name = code_to_name.get(dominant, "Unknown")
        key = slugify(name, existing_slugs, start)
        definitions[key] = {
            "code": dominant,
            "name_en": name,
            "name_id": name,
            "range": f"{start:04X}-{end:04X}",
            "unicode": True,
            "font": font_family_for_script(dominant, primary_name),
            "sample": sample,
            "sample_name": sample_name,
            "sample_codepoint": f"U+{sample_cp:04X}" if sample_cp is not None else None,
            "script_codes": codes,
            "script_names": [code_to_name.get(code, code) for code in codes],
            "source": "Unicode Character Database",
        }
    if not definitions:
        raise ValueError("No Unicode block definitions were generated.")
    return definitions


def wikidata_query() -> str:
    # Country -> language used (P2936) -> writing system (P282) -> ISO 15924 (P506).
    # Values remain explicitly source-attributed; absent relationships are not guessed.
    return """
SELECT DISTINCT
  ?countryCode2 ?countryCode3 ?countryLabel
  ?language ?languageLabel ?languageCode
  ?script ?scriptLabel ?scriptCode
WHERE {
  ?country wdt:P297 ?countryCode2;
           wdt:P2936 ?language.
  OPTIONAL { ?country wdt:P298 ?countryCode3. }
  ?language wdt:P282 ?script.
  ?script wdt:P506 ?scriptCode.
  OPTIONAL { ?language wdt:P220 ?languageCode. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 20000
""".strip()


def fetch_wikidata_relationships() -> tuple[list[dict[str, str]], dict[str, object]]:
    query = wikidata_query()
    url = WIKIDATA_ENDPOINT + "?" + urlencode({"query": query, "format": "json"})
    payload, final_url = fetch_text(
        url,
        headers={"Accept": "application/sparql-results+json"},
        timeout=180,
    )
    try:
        response = json.loads(payload)
        bindings = response["results"]["bindings"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Wikidata SPARQL returned an unreadable response.") from exc
    if not bindings:
        raise RuntimeError("Wikidata SPARQL returned no language/script/country relationships.")
    relationships: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in bindings:
        def value(key: str) -> str:
            return str(row.get(key, {}).get("value", "")).strip()

        country2 = value("countryCode2").upper()
        if not re.fullmatch(r"[A-Z]{2}", country2):
            continue
        language_uri = value("language")
        script_uri = value("script")
        language_id = language_uri.rsplit("/", 1)[-1] if language_uri else ""
        script_id = script_uri.rsplit("/", 1)[-1] if script_uri else ""
        script_code = value("scriptCode")
        if not language_id or not script_id or not script_code:
            continue
        key = (country2, language_id, script_code)
        relationships[key] = {
            "country_iso2": country2,
            "country_iso3": value("countryCode3").upper(),
            "country_label_en": value("countryLabel"),
            "language_id": language_id,
            "language_label_en": value("languageLabel"),
            "language_iso639_3": value("languageCode").lower(),
            "script_id": script_id,
            "script_label_en": value("scriptLabel"),
            "script_code": script_code,
            "country_source_property": "P297",
            "language_source_property": "P2936",
            "writing_system_source_property": "P282",
            "script_code_source_property": "P506",
            "source": "Wikidata",
            "source_url": f"https://www.wikidata.org/wiki/{language_id}",
        }
    results = sorted(relationships.values(), key=lambda item: (
        item["country_iso2"], item["language_id"], item["script_code"]
    ))
    if not results:
        raise RuntimeError("Wikidata results did not contain valid country/language/script records.")
    manifest = {
        "name": "Wikidata language, writing-system and country relationships",
        "query_endpoint": WIKIDATA_ENDPOINT,
        "query": query,
        "final_url": final_url.split("?", 1)[0],
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "properties": {
            "P2936": "language used in a place",
            "P282": "writing system used by a language",
            "P506": "ISO 15924 script code",
            "P297": "ISO 3166-1 alpha-2 country code",
            "P298": "ISO 3166-1 alpha-3 country code",
            "P220": "ISO 639-3 language code",
        },
        "records": len(results),
    }
    return results, manifest


def build_public_datasets(
    definitions: dict[str, dict[str, object]],
    relationships: list[dict[str, str]],
    unicode_version: str,
) -> tuple[dict[str, list[str]], list[dict[str, object]], dict[str, object]]:
    blocks_by_code: dict[str, set[str]] = collections.defaultdict(set)
    for block_id, definition in definitions.items():
        script_codes = definition.get("script_codes", [])
        if isinstance(script_codes, list):
            for script_code in script_codes:
                if script_code and script_code not in GENERIC_SCRIPT_CODES:
                    blocks_by_code[str(script_code)].add(block_id)

    countries: dict[str, set[str]] = collections.defaultdict(set)
    language_map: dict[str, dict[str, object]] = {}
    matched_relationships: list[dict[str, str]] = []
    for relationship in relationships:
        country_code = relationship["country_iso2"]
        language_id = relationship["language_id"]
        script_code = relationship["script_code"]
        block_ids = blocks_by_code.get(script_code, set())
        if block_ids:
            countries[country_code].update(block_ids)
            matched_relationships.append(relationship)

        language = language_map.setdefault(language_id, {
            "id": language_id,
            "name_en": relationship["language_label_en"],
            "iso639_3": relationship["language_iso639_3"],
            "wikidata_url": f"https://www.wikidata.org/wiki/{language_id}",
            "script_codes": set(),
            "script_names": set(),
            "country_codes": set(),
            "source": "Wikidata",
        })
        if relationship["script_code"]:
            language["script_codes"].add(script_code)
            language["script_names"].add(relationship["script_label_en"] or script_code)
        language["country_codes"].add(country_code)
        if not language.get("name_en") and relationship["language_label_en"]:
            language["name_en"] = relationship["language_label_en"]
        if not language.get("iso639_3") and relationship["language_iso639_3"]:
            language["iso639_3"] = relationship["language_iso639_3"]

    if not countries:
        raise RuntimeError(
            "No country-to-block relationships could be derived from Wikidata ISO 15924 codes. "
            "The existing published datasets were left untouched."
        )

    normalized_countries = {
        country_code: sorted(block_ids)
        for country_code, block_ids in sorted(countries.items())
        if block_ids
    }
    normalized_languages: list[dict[str, object]] = []
    for language in language_map.values():
        normalized_languages.append({
            **language,
            "script_codes": sorted(language["script_codes"]),
            "script_names": sorted(language["script_names"]),
            "country_codes": sorted(language["country_codes"]),
        })
    normalized_languages.sort(key=lambda item: (str(item["name_en"]).casefold(), str(item["id"])))

    unmatched = len(relationships) - len(matched_relationships)
    relationship_payload = {
        "metadata": {
            "dataset": "Wikidata language-writing-system-country relationships",
            "unicode_version_for_block_linking": unicode_version,
            "source": "Wikidata SPARQL",
            "license": "CC0 1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "matching_note": (
                "A country-to-block link is generated only when a Wikidata language/country "
                "relationship includes a script ISO 15924 code that matches a Unicode Script "
                "property observed in a block. Absence of a link is not evidence that a script "
                "is not used in that country."
            ),
            "records_from_source": len(relationships),
            "records_matched_to_unicode_blocks": len(matched_relationships),
            "records_without_block_match": unmatched,
        },
        "relationships": matched_relationships,
    }
    stats = {
        "country_count": len(normalized_countries),
        "language_count": len(normalized_languages),
        "wikidata_relationship_count": len(relationships),
        "matched_relationship_count": len(matched_relationships),
        "unmatched_relationship_count": unmatched,
    }
    return normalized_countries, normalized_languages, {"relationship_payload": relationship_payload, "stats": stats}


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the public World Script Explorer datasets.")
    parser.add_argument(
        "--unicode-version",
        default="latest",
        help="Use the latest stable UCD release or an exact version such as 18.0.0.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Repository root in which aksara.json and data/ are written (default: current directory).",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()

    try:
        unicode_version, ucd_base = resolve_unicode_version(args.unicode_version)
        ucd_texts, ucd_sources = download_ucd(unicode_version, ucd_base)
        blocks = parse_blocks(ucd_texts["Blocks.txt"])
        name_to_code, code_to_name = parse_script_aliases(ucd_texts["PropertyValueAliases.txt"])
        script_ranges = parse_range_property(ucd_texts["Scripts.txt"])
        extension_ranges = parse_range_property(ucd_texts["ScriptExtensions.txt"], value_is_codes=True)
        character_data = parse_unicode_data(ucd_texts["UnicodeData.txt"])
        definitions = build_definitions(
            blocks, script_ranges, extension_ranges, name_to_code, code_to_name, character_data
        )

        relationships, wikidata_manifest = fetch_wikidata_relationships()
        countries, languages, relationship_result = build_public_datasets(
            definitions, relationships, unicode_version
        )
        relationship_payload = relationship_result["relationship_payload"]
        stats = relationship_result["stats"]

        aksara_payload = {
            "definitions": definitions,
            "countries": countries,
            "metadata": {
                "unicode_version": unicode_version,
                "source": "Unicode Character Database (UCD)",
                "source_url": f"https://www.unicode.org/Public/{unicode_version}/ucd/",
                "generated_by": "scripts/build_datasets.py",
                "country_mapping_source": "Wikidata SPARQL (P2936 → P282 → P506; country code P297)",
                "country_mapping_note": (
                    "Mappings are evidence-backed links from public Wikidata statements and Unicode "
                    "Script properties. They are incomplete where source statements are missing; "
                    "they must not be interpreted as exclusive geographic ownership of a script."
                ),
                "licenses": {
                    "unicode": "Unicode License v3; retain attribution and license notice",
                    "wikidata": "CC0 1.0",
                },
            },
        }
        languages_payload = {
            "metadata": {
                "dataset": "Languages linked to public writing-system records",
                "source": "Wikidata SPARQL",
                "license": "CC0 1.0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "count": len(languages),
            },
            "languages": languages,
        }
        manifest = {
            "generated_by": "scripts/build_datasets.py",
            "unicode_version": unicode_version,
            "unicode_source": {
                "name": "Unicode Character Database (UCD)",
                "base_url": ucd_base,
                "license": "Unicode License v3",
                "license_url": "https://www.unicode.org/license.txt",
                "files": ucd_sources,
            },
            "relationship_source": wikidata_manifest,
            "counts": {
                "unicode_blocks": len(definitions),
                **stats,
            },
            "notes": [
                "Generated from public source datasets; no country/script links are manually inferred.",
                "Unicode blocks are codepoint ranges, not synonyms for writing systems or languages.",
                "Script-to-block relationships are derived from Unicode Script and ScriptExtensions data.",
                "A missing Wikidata relationship does not prove a script is absent from a country or language.",
                "Script font family values are best-effort Noto Sans family names; font availability varies.",
                "The data builder uses only Python's standard library.",
            ],
        }

        write_json(output_dir / "aksara.json", aksara_payload)
        write_json(output_dir / "data" / "languages.json", languages_payload)
        write_json(output_dir / "data" / "script_relationships.json", relationship_payload)
        write_json(output_dir / "data" / "source_manifest.json", manifest)

        print(f"Unicode UCD version: {unicode_version}")
        print(f"Unicode blocks generated: {len(definitions)}")
        print(f"Countries with sourced script/block links: {stats['country_count']}")
        print(f"Languages linked in Wikidata results: {stats['language_count']}")
        print(f"Public relationships matched to Unicode blocks: {stats['matched_relationship_count']}")
        print("Generated: aksara.json, data/languages.json, data/script_relationships.json, data/source_manifest.json")
        return 0
    except Exception as exc:  # noqa: BLE001 - print actionable message in CI as well.
        print(f"ERROR: dataset generation failed: {exc}", file=sys.stderr)
        print("No partial output is intentionally published; re-run after the source becomes available.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
