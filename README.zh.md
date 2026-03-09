# terraink_py

本项目是 [terraink](https://github.com/yousifamanuel/terraink) 的 Python 版本，同时提供一个独立的 Python 渲染器，无需依赖网站即可直接生成地图海报，输出格式支持 `png` 和 `svg`。

## 安装

![telegram-cloud-photo-size-5-6156789869284363624-w](https://github.com/user-attachments/assets/ee69b0b6-1264-4518-803c-cdc2bc3e4b64)


**从 PyPI 安装：**

```bash
pip install terraink_py
```

或使用 [uv](https://github.com/astral-sh/uv) 安装（推荐用于 CLI 工具）：

```bash
uv tool install terraink_py
```

## 使用方法

### 命令行使用

通过地名生成海报：

```bash
terraink \
  "甘井子区, 中国" \
  --theme midnight_blue \
  --layout print_a4_portrait \
  --distance-m 4000 \
  --format png svg \
  --output outputs/ganjingzi
```

也可以使用 `--location "..."` 参数指定地名，效果相同。

### Python 代码中使用

通过坐标生成海报：

```python
from pathlib import Path

from terraink_py import PosterRequest, generate_poster

result = generate_poster(
    PosterRequest(
        output=Path("outputs/ganjingzi"),
        formats=("png", "svg"),
        lat=38.862405,
        lon=121.513525,
        title="甘井子区",
        subtitle="中国",
        theme="midnight_blue",
        width_cm=21,
        height_cm=29.7,
        distance_m=4000,
        include_buildings=True,
    )
)

print(result.files)
```

## 开发

本项目使用 `uv` 进行依赖管理：

```bash
uv sync --all-groups
```

使用 `prek` 运行统一检查：

```bash
uv run prek run --all-files
```

然后通过以下命令运行：

```bash
uv run terraink --help
```

## 注意事项

- Python 渲染器直接使用 Nominatim 和 Overpass API，因此适用于城市和区域级别的地图海报，而非全球范围导出。
- `svg` 输出为真正的矢量几何图形，而非浏览器截图封装在 SVG 中。
- 中文地名现在会自动回退到 macOS/Linux 系统上常见的 CJK 字体；如果您的设备缺少字体支持，可通过 `--font-file /path/to/font.ttf` 指定字体文件。
- PyPI 包名为 `terraink_py`，而 CLI 命令为 `terraink`。
