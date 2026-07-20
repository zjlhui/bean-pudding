# Bean Pudding

把普通图片转换成拼豆图纸：先生成接近 Photoshop 缩放观感的低分辨率 RGB 像素图，再把每个格子匹配到 Mard 拼豆色号，并输出带坐标、网格、色号和用量统计的成品图。

## 当前策略

1. 像素化前使用 `edge` 去杂色：平滑大面积噪点，同时保留边缘和暗线对比。
2. 低分辨率 RGB 图使用高质量 LANCZOS 缩放，尽量接近 Photoshop 重新设置图像大小的观感。
3. 标色号前按整张图统计 RGB：LAB 色差接近的颜色先组成全局色组，组内统一采用出现更稳定的同一个 Mard 色号。
4. 标号后再做局部相似色合并，把相邻且 LAB 距离接近的小色差并到邻近主体色。
5. 默认使用 Mard 色卡、不排除色号，最终最多使用 `10` 个颜色；把 `FINAL_COLOR_LIMIT` 设为 `0` 可取消限制。

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 微信小程序开发版

微信开发者工具打开项目根目录后，会读取 `project.config.json`，并自动把 `Mini-program development/` 作为小程序源码目录。小程序图标为 `Mini-program development/Icon.png`。

先在项目根目录启动本地 Python 服务：

```powershell
python -m server
```

启动成功后可以访问：

- `http://127.0.0.1:8000/api/health`：服务状态。
- `http://127.0.0.1:8000/docs`：FastAPI 接口调试页面。

再回到微信开发者工具点击“编译”。首页右上角显示“服务正常”后，即可选择图片并生成图纸。当前最长边提供 `29`、`52` 和 `78` 三档，颜色数量可设置为不限或 `4~24` 色；三档尺寸集中配置在 `Mini-program development/config.js` 的 `TARGET_MAX_SIZE_OPTIONS` 中。

小程序中的“相近色统一”有“细节优先 / 均衡 / 精简优先”三档，对应 LAB 色差阈值 `4 / 6 / 8`。它只会让彼此接近的 RGB 使用同一个拼豆色，不保证最终颜色数；“最终色号上限”则是整张图允许使用的 Mard 色号硬上限，必要时会把更多颜色压缩到该数量以内。

小程序当前连接微信云托管的 HTTPS 测试域名。正式发布前，需要在云托管中绑定自定义域名，并同步替换 `Mini-program development/config.js` 中的 `API_BASE_URL`。本地接口调试仍可使用 `http://127.0.0.1:8000`，但不能把该地址用于体验版或正式版。

生成接口会返回色号图、RGB 像素图和颜色统计；本地结果位于 `server/runtime/jobs/`，默认保留 24 小时。该目录及小程序私钥文件均已加入忽略规则，不应提交或打包。

### 微信云托管部署参数

云托管使用项目根目录的 `Dockerfile` 构建后端：

- 目标目录：留空（项目根目录）。
- Dockerfile 名称：`Dockerfile`。
- 端口：`8080`。Docker 容器默认读取 `PORT` 环境变量，本地直接运行服务仍使用 `8000`。
- 首次部署时环境变量可以留空；获得正式 HTTPS 地址后，添加 `PUBLIC_BASE_URL=https://正式地址`，值末尾不要带 `/`。
- 健康检查路径：`/api/health`。

当前生成文件保存在容器本地目录。正式扩大到多个实例前，应迁移到云存储；在此之前将服务最大实例数保持为 `1`。

## 运行

```powershell
python -m bean_pudding images\test\test1.jpg --title "test1 拼豆图"
python -m bean_pudding images\test\test2.jpg --title "test2 拼豆图"
```

测试图片时运行的是模块入口 `python -m bean_pudding ...`，它内部调用 `bean_pudding/cli.py`。如果在 IDE 里想找入口文件，就是 `bean_pudding/cli.py`。

如果不想每次都在命令里写参数，可以直接改 `bean_pudding/cli.py` 开头的默认配置：

```python
TARGET_MAX_SIZE = 78
FINAL_COLOR_LIMIT = 10
GLOBAL_COLOR_MERGE_DISTANCE = 6.0
OUTLINE_SIMPLIFY = True
BRIGHT_DETAIL_RECOVERY = True
SOURCE_COVERAGE_RECOVERY = True
NEAR_WHITE_CLEANUP = True
```

`TARGET_MAX_SIZE` 是生成图纸最长边的豆格像素数；`FINAL_COLOR_LIMIT` 是最终 Mard 色号数量上限，`0` 表示不限制，否则最多使用 `FINAL_COLOR_LIMIT` 个颜色。
`GLOBAL_COLOR_MERGE_DISTANCE` 是同一张图内相近 RGB 的全局合并阈值，实际使用 LAB 感知色差；默认 `6.0`，设为 `0` 可关闭，数值越大合并越积极。
`OUTLINE_SIMPLIFY` 会统一与空白背景相邻的一格外轮廓，并在大主体上清除紧贴外圈的第二层平行深色，使描边尽量保持一格宽；眼睛、领带和衣服纹理等内部细节不会被统一。
`BRIGHT_DETAIL_RECOVERY` 会恢复被相邻深色描边污染的封闭近白细节，例如白色绳芯和文字内部留白；外部背景不会参与恢复。
`SOURCE_COVERAGE_RECOVERY` 会统计每个豆格在原图中覆盖的完整区域；当区域内存在明确的非白主体色，而缩图结果误变成近白色时，将其恢复为区域主色。它使用区域覆盖率而不是单个坐标取样。
`NEAR_WHITE_CLEANUP` 会把白色主体周围的小块近白过渡色并回主体白色，适合清理腮红、文字留白附近的抗锯齿杂色。

默认输出路径会按输入图片名称自动创建。例如输入 `images\test\test1.jpg`，会生成到 `outputs\test1\`：

- `test1_pattern.jpg`
- `test1_pattern_rgb.jpg`
- `test1_summary.csv`

每次会输出两张图：

- `-o` 指定的图片：匹配 Mard 色号后的图纸。
- 自动生成的 `_rgb` 图片：标色号前的 RGB 像素图，只带坐标和网格。

## 常用参数

- `--max-size`：最长边豆数，默认 `78`。
- `--width/--height`：指定精确豆数，不能超过 `--max-size`。
- `--denoise`：像素化前去杂色方式，默认 `edge`；可选 `none`、`median`、`smooth`、`edge`、`bilateral`。
- `--denoise-strength`：去杂色强度，默认 `2`；设为 `0` 等于关闭。
- `--denoise-contrast`：去杂色后的对比度回补，默认 `1.18`。
- `--denoise-sharpness`：去杂色后的锐度回补，默认 `1.35`。
- `--pre-colors`：像素化前先把高清图合并到多少个代表色，默认 `12`。
- `--pre-mode-filter-size`：像素化前局部众数滤波窗口，默认 `0` 关闭。
- `--palette-limit`：最终最多使用多少个 Mard 色，默认读取 `FINAL_COLOR_LIMIT`；`0` 表示不限制。
- `--global-color-merge-distance`：整张图内相近 RGB 的 LAB 合并阈值，默认读取 `GLOBAL_COLOR_MERGE_DISTANCE`；`0` 表示关闭。
- `--exclude-colors`：从匹配里排除的色号，默认空字符串，即不排除。
- `--local-merge-distance`：标号后局部相似色合并的 LAB 距离，默认 `14`。
- `--local-merge-threshold`：周围至少多少个相似邻居才合并，默认 `2`。
- `--outline-simplify/--no-outline-simplify`：是否统一描边色，默认读取 `OUTLINE_SIMPLIFY`。
- `--outline-max-luma`：选择主描边色时允许的最高亮度，默认 `135`。
- `--outline-luma-gap`：把浅色抗锯齿边缘并入主描边色所需的最低亮度差，默认 `26`。
- `--bright-detail-recovery/--no-bright-detail-recovery`：是否恢复缩图时被深色描边压暗的封闭近白细节。
- `--source-coverage-recovery/--no-source-coverage-recovery`：是否用原图区域主色纠正缩图和标色阶段产生的错误近白色。
- `--near-white-cleanup/--no-near-white-cleanup`：是否把小块近白过渡色并入占优势的相邻白色。
- `--detail-min-share`：高对比细节至少占一个豆格区域的比例，默认 `0` 关闭。
- `--detail-luma-gap`：细节比区域平均亮度暗多少才保护，默认 `38`。
- `--detail-max-luma`：被保护细节的最高亮度，默认 `105`。
- `--detail-base-min-luma`：普通标色结果足够亮时才允许暗色细节覆盖，默认 `205`。
- `--pixel-method`：像素匹配方式，默认 `global`；`global` 是 RGB 缩图后逐像素标色，`vote` 是较慢的原图区域投票，`resize` 是旧版缩图方式。
- `--vote-threshold`：区域内主色票数占比达到多少就采用主色，默认 `0.35`。
- `--empty-background`：`corners` 按四角背景留空，`white` 按白色留空，`none` 不留空。

## 调参示例

更强调原始 Photoshop 风格：

```powershell
python -m bean_pudding input.jpg --pixel-method global --palette-limit 0
```

减少颜色数量：

```powershell
python -m bean_pudding input.jpg --palette-limit 10 --local-merge-distance 16
```

加强文字和领带等暗色细节：

```powershell
python -m bean_pudding input.jpg --detail-min-share 0.06 --detail-luma-gap 32
```

## 色表来源

默认使用 `data/mard_palette.csv`，编号范围为 `A1` 到 `M15`。CSV 字段为 `code,name,hex,r,g,b,brand`。
