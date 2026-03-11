The repo is python version of [terraink](https://github.com/yousifamanuel/terraink)

[中文文档](README.zh.md)
now also ships a standalone Python renderer that skips the website entirely and writes map posters directly to `png` and `svg`.


![telegram-cloud-photo-size-5-6156580721556917384-y](https://github.com/user-attachments/assets/a1a59cc4-8571-44fc-b73e-42b4e2fa8265)


### Installation

**Install from PyPI:**

```bash
pip install terraink_py
```

Or with [uv](https://github.com/astral-sh/uv) (recommended for CLI tools):

```bash
uv tool install terraink_py
```

### Usage

Generate a poster from a place name:

```bash
terraink \
  "Ganjingzi District, China" \
  --theme midnight_blue \
  --layout print_a4_portrait \
  --language en \
  --distance-m 4000 \
  --format png svg \
  --output outputs/ganjingzi
```

`--location "..."` still works; the positional argument is just a shorter alias.

### Development

Use `uv` in this repo:

```bash
uv sync --all-groups
```

Run the shared checks with `prek`:

```bash
uv run prek run --all-files
```

Then run via:

```bash
uv run terraink --help
```

Generate from coordinates in Python code:

```python
from pathlib import Path

from terraink_py import PosterRequest, generate_poster

result = generate_poster(
    PosterRequest(
        output=Path("outputs/ganjingzi"),
        formats=("png", "svg"),
        lat=38.862405,
        lon=121.513525,
        title="Ganjingzi District",
        subtitle="China",
        theme="midnight_blue",
        width_cm=21,
        height_cm=29.7,
        distance_m=4000,
        include_buildings=True,
    )
)

print(result.files)
```

Notes:

- The Python renderer uses Nominatim + Overpass directly, so it is designed for city and regional posters rather than world-scale exports.
- `svg` output is true vector geometry, not a browser screenshot wrapped in SVG.
- Place label language defaults to auto-detect from your title/subtitle/query. Use `--language en` or `--language zh` to override it.
- Chinese place names now auto-fallback to common CJK system fonts on macOS/Linux; if your machine still lacks glyph coverage, pass `--font-file /path/to/font.ttf`.
- The PyPI package name is `terraink_py`, while the CLI command is `terraink`.
