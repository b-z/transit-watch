# transit-watch

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](../../LICENSE) [![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-db61a2?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/b-z)

[English](../../README.md) · [中文](../zh/README.md)

**ISS の太陽面・月面通過を撮るために、どこに立ち、いつシャッターを切るか。**

transit-watch は、今後 2 週間のうちに国際宇宙ステーション（ISS）、中国宇宙ステーション「天宮」、ハッブル宇宙望遠鏡が自宅近くで太陽や月の前を横切る機会を探します。撮る価値のある通過ごとに、次の情報を出します。

- **撮影地点**：中心線上で自宅に最も近い**陸上**の点。その地点の実際の標高で中心線を計算し直します。
- 0.01 秒単位の**時刻**、その地点から見たステーションの**視直径**、通過時間、可視帯の幅。
- その地点・その時間の**天気**（晴れ、晴れ間あり、曇り、雨）。
- **2 枚の画像**：中心線の地図と、太陽面・月面のプレビュー。プレビューではステーションを実寸の比率で描き、カメラのコマごとにシルエットを並べます。
- **インタラクティブマップ**（全通過を 1 つの HTML に収録）：任意の点をタップするか現在地を使うと、その地点の**実際の地面の高さ**での中心線の方向と距離、可視帯の内外、そこでの中心時刻を表示し、その地点から見た太陽面・月面のプレビュー（カメラのコマごとのステーション）も描きます。

<p>
<img src="../images/example-map.jpg" alt="地図：中心線、可視帯、自宅、撮影地点" width="100%">
</p>
<p align="center">
<img src="../images/example-disk.png" alt="月面プレビュー：輝面 72% の月を毎秒 20 コマで横切る ISS" width="48%">
</p>

中心線は公開データ（CelesTrak の軌道要素、JPL 暦、IERS の地球回転パラメータ）からローカルで計算します。ウェブサイトのスクレイピングは一切行いません。

## インストール

Python 3.11 以降が必要です。

```bash
uv tool install git+https://github.com/b-z/transit-watch
# または：pipx install git+https://github.com/b-z/transit-watch
```

画像はヘッドレスの Google Chrome または Chromium で描画します。ブラウザがなくても、テキストのレポートは作成されます。

## 使い方

```bash
transit-watch init      # 自宅の座標、タイムゾーン、言語、各しきい値を対話式で設定
transit-watch run       # レポートを表示し、画像と一緒に保存
```

`init` は引数だけで実行することもできます。

```bash
transit-watch init -y --lat 35.6812 --lon 139.7671 --elevation 5 --timezone Asia/Tokyo --language ja
```

レポートは Markdown と JSON で `~/transit-watch/reports/` に保存され、画像は日付ごとのフォルダに、インタラクティブマップは `<日付>-map.html` に入ります。スマートフォンの位置情報を使うには HTTPS のサイト（静的ファイルを置けるサーバーなら何でも）に置いてください。1 日 1 回の実行をおすすめします（cron、launchd、定期タスクなど）。軌道予報が信頼できるのは数日先までなので、通過当日にもう一度実行してください。

### Claude Code と使う

このリポジトリは Claude Code のプラグインでもあります。付属のスキルが初期設定と予報の実行・要約を行い、毎日のレポートも設定できます。

```
/plugin marketplace add b-z/transit-watch
/plugin install transit-watch@transit-watch
```

あとは「今週、撮る価値のある ISS の月面通過はある？」のように尋ねるだけです。

## 設定

設定ファイルは `~/.config/transit-watch/config.toml` です（環境変数 `TRANSIT_WATCH_CONFIG` でも指定できます）。`transit-watch init` がすべての項目を既定値つきで書き出します。

| キー | 既定値 | 意味 |
|---|---|---|
| `location.latitude`、`longitude`、`elevation_m`、`timezone` | — | 自宅。距離はここから測ります。 |
| `search.days` | 14 | 何日先まで探すか。 |
| `search.min_altitude_deg` | 15 | これより低い通過は報告しません。 |
| `search.satellites` | ISS、天宮、ハッブル | NORAD 番号。先頭の 1 機に `rules.iss` のしきい値を使います。 |
| `rules.iss.sun` | 50″、40 km | 最小の視直径と、中心線までの最大距離。 |
| `rules.iss.moon` | 30″、160 km、輝面 60% | 撮る価値があるのは満月か満月に近い月だけです。 |
| `rules.other.sun` / `moon` | 8″ / 6″、距離は同じ | ほかの宇宙機はずっと小さく見えます。 |
| `grades` | 60″ / 50″ / 30″ | 絶好 / 良好 / まずまず。天頂付近の ISS は約 60″ です。 |
| `model.mode` | `strict` | `strict`（厳密）または `transit-finder`。後述。 |
| `model.compare_transit_finder` | true | もう一方のモデルの中心線も比較として表示します。 |
| `spot.land_provider` | `auto` | 陸地判定に使う標高データ：日本国内は国土地理院、国外は Open-Meteo、または `none`。 |
| `render.fps` | 20 | プレビューでシルエットを並べる間隔に使うカメラのフレームレート。 |
| `render.chrome` | 自動 | Chrome または Chromium のパス。 |
| `output.dir`、`output.language` | `~/transit-watch/reports`、`en` | 出力先と言語（`en`、`zh`、`ja`）。 |

## 仕組み

ある瞬間に、ステーションが太陽や月の中心にぴったり重なって見える観測者は、「天体の中心 → ステーション」を結ぶ直線を地面まで延ばした点にいます。ステーションが動くと、この点が地上に**中心線**を描きます。transit-watch は自宅の近くを通る中心線を見つけたあと、次の処理を行います。

1. 自宅に最も近い中心線上の点から線に沿って進み、最初の陸地を探す。
2. その地点の高さで中心線を計算し直し、自分の地面の高さでちょうど中心線上に来る点を求める。高度 40° のとき、観測点が 300 m 高いと中心線は横に約 360 m ずれます。高さは楕円体高で、日本国内では DEM の標高に国土地理院のジオイド高（東京周辺で約 37 m、これだけで中心線が 20〜45 m ずれる）を加えます。
3. **その地点で**、中心通過の時刻、ステーションの視直径と見かけの速さ、通過時間、可視帯の幅を計算する。
4. その地点・その時間の雲量と降水確率を Open-Meteo から取得する。

衛星の位置は CelesTrak の最新 TLE から SGP4 で計算し、太陽と月の位置は skyfield 経由で JPL DE421 から求めます。

## 精度

**モデル。** `strict` モデルは IERS の UT1、歳差・章動、光行時間、光行差を考慮します。観測地点から見た太陽と月の位置は、JPL Horizons と 0.05″ 以内で一致し、地上では 1 m よりはるかに小さな差です。

**transit-finder モード。** [transit-finder.com](https://transit-finder.com) は通過撮影で最もよく使われているツールです。`transit-finder` モデルはその計算の取り決めを再現したもので、2026 年 10 月の比較では同サイトの中心線 24 本すべてと約 1 m で一致しました。`strict` との主な違いは、月の位置が約 69 秒遅れていること（UTC を暦の時刻系として使用）と、太陽・月に光行差と章動が入っていないことです。東京周辺の 30 日分の通過で、両モデルの差は次のとおりでした。

| | 中央値 | 最大 |
|---|---|---|
| ISS × 太陽 | 54 m | 64 m |
| ISS × 月 | 73 m | 304 m |
| その他 × 太陽 | 39 m | 226 m |
| その他 × 月 | 107 m | 365 m |

**実際の撮影で精度を決めるのは軌道要素です。** TLE はフィッティングの結果で、エポックから日がたつほど予報誤差が大きくなり、上の差を超えることもよくあります。通過当日にもう一度実行し、最新の TLE を使ってください。

## データとクレジット

- 軌道要素：[CelesTrak](https://celestrak.org)。CelesTrak の求めに従い、ダウンロードは 2 時間キャッシュします。
- 暦：JPL DE421（[skyfield](https://rhodesmill.org/skyfield/) 経由）。地球回転パラメータ：[USNO](https://maia.usno.navy.mil) の IERS Bulletin A。
- 天気と日本国外の標高：[Open-Meteo](https://open-meteo.com)（CC BY 4.0）。
- 日本国内の標高と地図：[地理院タイル](https://maps.gsi.go.jp/development/ichiran.html)と[標高タイル](https://maps.gsi.go.jp/development/demtile.html)：1 m の航空レーザ DEM（DEM1A）がある所はそれを、ない所は 5 m または 10 m を使い、双線形補間してローカルにキャッシュします。国外の地図：Esri World Street Map。地図の描画には [Leaflet](https://leafletjs.com) を使っています。

本プロジェクトは独立したもので、transit-finder.com とは関係がなく、同サイトにアクセスすることもありません。

## プロジェクトを支援する

transit-watch は空き時間に保守しています。通過の撮影に役立ったら、[GitHub Sponsors](https://github.com/sponsors/b-z) や WeChat で支援していただけるとうれしいです。支援は任意で、Issue やプルリクエストの扱いには影響しません。

<table><tr>
<td align="center" valign="middle"><a href="https://github.com/sponsors/b-z"><img src="https://img.shields.io/badge/GitHub%20Sponsors-%E2%9D%A4%20Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="Sponsor on GitHub" height="36"></a></td>
<td align="center" valign="middle"><img src="../images/wechat-reward.jpg" alt="WeChat 赞赏コード" width="180"></td>
</tr></table>

## ライセンス

[GPL-3.0-or-later](../../LICENSE)。
