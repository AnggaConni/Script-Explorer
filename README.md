# World Script Explorer 🌍

An interactive, global explorer for Unicode writing-system blocks and publicly sourced language/script relationships.

Live app: https://anggaconni.github.io/Script-Explorer/  
Writing Practice Studio: https://anggaconni.github.io/Script-Explorer/writing-practice.html  
SVG favicon: [favicon.svg](https://github.com/AnggaConni/Script-Explorer/blob/main/favicon.svg)

## What it does

- Explore Unicode blocks and sample characters.
- View country-to-script/block relationships backed by public structured data.
- Browse generated metadata and public-data source records.
- Open the Writing Practice Studio in a new tab with the selected block's name, code, range, sample character, and font passed from the explorer.
- Use an SVG favicon showing a calligraphy pen writing Javanese script on a white canvas, with SEO and Open Graph/Twitter metadata on both pages.
- Reference a root-level `thumbnail.png` for link previews; upload that image to the repository root when ready.
- Practise with mouse, touch, or stylus using a trace guide, undo/clear, pen controls, and PNG export.
- Follow an Iqro-style character sequence for the selected Unicode block, with previous/next controls, a selectable character grid, progress, and filters for letters/marks or all printable assigned characters.
- Keep the browser app static and lightweight: no private API keys or application server are required.

## Automated public-data pipeline

The generated files are **not intended to be edited manually**. The Python builder retrieves public source data, validates it, and writes the datasets consumed by the website.

### Sources

1. **Unicode Character Database (UCD)** — official files: Blocks.txt, Scripts.txt, ScriptExtensions.txt, UnicodeData.txt, and PropertyValueAliases.txt.
   - Latest stable data: https://www.unicode.org/Public/UCD/latest/ucd/
   - Version archive: https://www.unicode.org/Public/
   - Terms: https://www.unicode.org/license.txt
2. **Wikidata SPARQL** — publicly available structured statements relating countries, languages, writing systems, and ISO 15924 script codes.
   - Endpoint: https://query.wikidata.org/
   - Query relationships: country language used (P2936) → language writing system (P282) → script ISO 15924 code (P506); country ISO alpha-2 (P297) / alpha-3 (P298) and language ISO 639-3 (P220) where available.
   - Structured data license: CC0 1.0, https://creativecommons.org/publicdomain/zero/1.0/

The pipeline uses the Python standard library only. Source datasets are fetched at run time; no source data needs to be pasted into a notebook.

### Writing Practice Studio

Each script/block card has a **Practice Writing / Latihan Menulis** button. It opens `writing-practice.html` in a separate tab and passes the selected metadata through URL parameters, without a backend. The canvas uses Pointer Events for mouse, touchscreen, and stylus input. Users can change the guide character/text, toggle the faint guide, undo the last stroke, clear the canvas, adjust ink and pen size, and export the canvas as a PNG image. The drawing stays in the browser unless the user exports it; no drawing data is uploaded.

### Generated files

| File | Purpose |
| --- | --- |
| aksara.json | Website dataset: Unicode block definitions, country-code mappings, and source/version metadata |
| data/languages.json | Language records returned by the public Wikidata query |
| data/script_relationships.json | Matched, source-attributed country/language/script relationships |
| data/source_manifest.json | Source URLs, licenses, source checksums, query metadata, and record counts |
| data/UNICODE-LICENSE.txt | Unicode license notice distributed with the generated Unicode-derived dataset |

### Run locally

Python 3.10+ is recommended. Internet access is required to retrieve official UCD files and query Wikidata.

    python scripts/build_datasets.py --unicode-version latest

To rebuild using a fixed Unicode release:

    python scripts/build_datasets.py --unicode-version 18.0.0

The requested Unicode version must be an exact stable version such as 18.0.0, or latest. The generator resolves latest to a versioned UCD directory before downloading the source files, and records SHA-256 checksums in the manifest. It validates the downloaded files and the public relationships before writing outputs.

The historical filename “Phyton UNICODE.py” is retained as a compatibility wrapper; it forwards to scripts/build_datasets.py.

### Automatic update and manual force-run

GitHub Actions checks the public data monthly and runs on relevant pipeline changes. It commits generated files only when source data or the resulting datasets change.

To force a refresh at any time:

1. Open the repository's **Actions** tab.
2. Select **Refresh public datasets**.
3. Select **Run workflow**.
4. Use latest for the latest stable UCD, or enter an exact version such as 18.0.0.
5. Start the workflow.

The ISO alpha-3 to alpha-2 crosswalk is also generated from Wikidata, so the map does not rely on the old incomplete hardcoded country-code list. The workflow requires no API token for the public sources. Its GitHub token has repository contents-write permission so it can publish updates, while the workflow explicitly stages only generated dataset files. A failed download, invalid dataset, or failed public relationship query stops the run so it cannot publish a partial update. Re-run the workflow if a public endpoint is temporarily unavailable.

## Interpretation and data quality

- A Unicode **block is not the same thing as a writing system, language, ethnicity, or country**. The app displays blocks because that is the granularity of its character explorer.
- Script-to-block links are derived from UCD Scripts.txt and ScriptExtensions.txt.
- Country mappings are generated only when public Wikidata statements provide a country/language/script relationship with a matching ISO 15924 script code. No missing relationship is filled by guessing.
- A missing country/script result is **not evidence** that a script is not used in that place. Public catalogues can be incomplete or inconsistent.
- Wikidata records are not a substitute for community validation or specialist linguistic review. Use them as discoverable references, not authoritative claims about cultural ownership.
- Font family names are best-effort Noto Sans family suggestions. Fonts may be unavailable for some historical or less-supported scripts.

## Contributing

Improvements to the generator and validation logic are welcome. Please keep generated datasets reproducible and avoid manually editing generated outputs. When adding a new source, document its URL, licensing/attribution requirements, data model, and failure behavior in the manifest and README.

## License

See LICENSE for the repository's code license. Third-party data used to generate the website remains subject to the original provider's terms; see the source manifest for details.
