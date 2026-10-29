# transit-watch

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](../../LICENSE) [![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-db61a2?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/b-z)

[English](../../README.md) · [日本語](../ja/README.md)

**拍国际空间站凌日、凌月：该站在哪里，什么时候按快门。**

transit-watch 会在接下来两周里，搜索国际空间站（ISS）、天宫空间站和哈勃望远镜从你家附近的太阳或月亮前面经过的时刻。每一次值得拍的凌日/凌月，它都会给出：

- **机位**：中心线上离家最近、而且**在陆地上**的点，并按这个点的实际海拔重算中心线；
- **时刻**（精确到 0.01 秒），以及在机位看到的空间站**视角大小**、穿越时间和可见带宽度；
- 机位在那个小时的**天气**（晴、多云、阴、雨）；
- **两张图**：中心线地图，以及日/月面预览图。预览图里的空间站按真实比例绘制，按相机帧率每帧画一个剪影；
- **交互地图**（所有事件放在一个 HTML 文件里）：点地图上任意一点，或跟随手机定位，按该点的**实际地面高度**算出中心线在哪个方向、多远，是否在可见带内，以及那里的中心时刻。

<p>
<img src="../images/example-map.jpg" alt="地图：中心线、可见带、家和机位" width="100%">
</p>
<p align="center">
<img src="../images/example-disk.png" alt="月面预览：ISS 以每秒 20 帧穿过照亮 72% 的月亮" width="48%">
</p>

中心线完全在本地用公开数据计算（CelesTrak 轨道、JPL 星历、IERS 地球定向参数），不抓取任何网站。

## 安装

需要 Python 3.11 或更新版本：

```bash
uv tool install git+https://github.com/b-z/transit-watch
# 或：pipx install git+https://github.com/b-z/transit-watch
```

图片用无头 Google Chrome 或 Chromium 渲染。没有浏览器时，仍会生成文字报告。

## 快速上手

```bash
transit-watch init      # 询问家的坐标、时区、报告语言和各项阈值
transit-watch run       # 输出报告，并连同图片一起保存
```

`init` 也可以不交互，直接用参数：

```bash
transit-watch init -y --lat 35.6812 --lon 139.7671 --elevation 5 --timezone Asia/Tokyo --language zh
```

报告以 Markdown 和 JSON 两种格式保存在 `~/transit-watch/reports/`，图片按日期放在子文件夹里，交互地图是 `<日期>-map.html`。想在手机上用定位，需要把它放到 HTTPS 网站上（任何静态网页服务器都行）。建议每天运行一次（cron、launchd、定时任务都行）：轨道预报只在几天内可靠，凌日当天要再跑一次。

### 配合 Claude Code 使用

这个仓库同时也是一个 Claude Code 插件。插件里的 skill 会完成首次配置、运行预报并总结结果，也能帮你设置每日报告。

```
/plugin marketplace add b-z/transit-watch
/plugin install transit-watch@transit-watch
```

之后直接问就行，比如“这周有值得拍的 ISS 凌月吗？”

## 配置

配置文件在 `~/.config/transit-watch/config.toml`（也可以用环境变量 `TRANSIT_WATCH_CONFIG` 指定）。`transit-watch init` 会把所有选项连同默认值一起写进去。

| 键 | 默认值 | 含义 |
|---|---|---|
| `location.latitude`、`longitude`、`elevation_m`、`timezone` | — | 家的位置。距离都从这里算。 |
| `search.days` | 14 | 往后搜索多少天。 |
| `search.min_altitude_deg` | 15 | 低于这个高度角的事件不报。 |
| `search.satellites` | ISS、天宫、哈勃 | NORAD 编号。第一个用 `rules.iss` 的阈值。 |
| `rules.iss.sun` | 50″、40 km | 最小视角；中心线离家最远多少。 |
| `rules.iss.moon` | 30″、160 km、照亮 60% | 只有满月或凸月才值得拍。 |
| `rules.other.sun` / `moon` | 8″ / 6″，距离相同 | 其他航天器小得多。 |
| `grades` | 60″ / 50″ / 30″ | 绝佳 / 不错 / 一般。ISS 在头顶附近时约 60″。 |
| `model.mode` | `strict` | `strict`（严格）或 `transit-finder`，见下文。 |
| `model.compare_transit_finder` | true | 同时给出另一个模型的中心线作对照。 |
| `spot.land_provider` | `auto` | 判断陆地用的海拔数据：日本境内用国土地理院，境外用 Open-Meteo，或 `none`。 |
| `render.fps` | 20 | 相机帧率，决定预览图里剪影的间隔。 |
| `render.chrome` | 自动 | Chrome 或 Chromium 的路径。 |
| `output.dir`、`output.language` | `~/transit-watch/reports`、`en` | 报告目录；语言可选 `en`、`zh`、`ja`。 |

## 原理

任一时刻，能看到空间站正好压在日面或月面中心的观测者，都位于“天体中心 → 空间站”这条直线延长到地面的交点上。空间站一动，这个交点就在地面上扫出一条**中心线**。transit-watch 先找出从家附近经过的中心线，然后：

1. 从中心线上离家最近的点出发，沿线找到第一个陆地点；
2. 按机位高度重算中心线，并求出“按自身地面高度正好落在中心线上”的点：高度角 40° 时，观测点高 300 m，中心线会横向平移约 360 m。高度用椭球高：日本境内在 DEM 海拔上加国土地理院的大地水准面高（东京一带约 37 m，单这一项就会让中心线偏 20–45 m）；
3. 在**这个机位**计算凌日中心时刻、空间站的视角和视速度、穿越时间，以及可见带宽度；
4. 向 Open-Meteo 查询机位在那个小时的云量和降水概率。

卫星位置用 SGP4 由 CelesTrak 最新的 TLE 推算；日月位置用 skyfield 读取 JPL DE421 星历。

## 精度

**模型本身。** `strict` 模型使用 IERS 的 UT1、岁差、章动、光行时和光行差。它算出的日月站心位置与 JPL Horizons 相差在 0.05″ 以内，换算到地面远小于 1 米。

**transit-finder 模式。** [transit-finder.com](https://transit-finder.com) 是凌日摄影师最常用的工具。`transit-finder` 模型复现了它的计算约定：在 2026 年 10 月的对比中，它算出的中心线与该网站给出的 24 条全部吻合，误差约 1 米。它与 `strict` 的主要区别是：月亮的位置晚了约 69 秒（把 UTC 当作星历时间），另外日月都没有考虑光行差和章动。东京附近 30 天内的凌日/凌月，两个模型的差别如下：

| | 中位数 | 最大 |
|---|---|---|
| ISS 凌日 | 54 m | 64 m |
| ISS 凌月 | 73 m | 304 m |
| 其他航天器凌日 | 39 m | 226 m |
| 其他航天器凌月 | 107 m | 365 m |

**实际拍摄时，真正限制精度的是轨道数据。** TLE 是拟合出来的，离历元每多一天，预报误差就会增大，往往超过上表里两个模型之间的差。凌日当天请再跑一次，用最新的 TLE。

## 数据来源与致谢

- 轨道：[CelesTrak](https://celestrak.org)。按 CelesTrak 的要求，下载结果缓存 2 小时。
- 星历：JPL DE421，通过 [skyfield](https://rhodesmill.org/skyfield/) 读取。地球定向参数：[USNO](https://maia.usno.navy.mil) 发布的 IERS Bulletin A。
- 天气，以及日本境外的海拔：[Open-Meteo](https://open-meteo.com)（CC BY 4.0）。
- 日本境内的海拔和地图：[国土地理院瓦片与 DEM](https://maps.gsi.go.jp/development/ichiran.html)（地理院タイル）。境外地图：Esri World Street Map。地图用 [Leaflet](https://leafletjs.com) 绘制。

这是一个独立项目，与 transit-finder.com 没有任何关联，也不会访问该网站。

## 支持这个项目

transit-watch 是在业余时间维护的。如果它帮你拍到了凌日，欢迎通过 [GitHub Sponsors](https://github.com/sponsors/b-z) 或微信赞赏支持。赞助完全自愿，不会影响 Issue 和 Pull Request 的处理。

<table><tr>
<td align="center" valign="middle"><a href="https://github.com/sponsors/b-z"><img src="https://img.shields.io/badge/GitHub%20Sponsors-%E2%9D%A4%20Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="Sponsor on GitHub" height="36"></a></td>
<td align="center" valign="middle"><img src="../images/wechat-reward.jpg" alt="微信赞赏码" width="180"></td>
</tr></table>

## 许可证

[GPL-3.0-or-later](../../LICENSE)。
