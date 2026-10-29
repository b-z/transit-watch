---
name: transit-watch
description: Forecast ISS / Tiangong / Hubble transits across the Sun and Moon near the user, with the exact spot to stand on the centerline, the time to 0.01 s, the station's apparent size, weather, a map and a disk preview. Use when the user asks about ISS or space station transits, solar or lunar transit photography, where to shoot a transit, or wants a daily transit report. Handles first-time setup (home coordinates and thresholds) and scheduling.
---

# transit-watch

The `transit-watch` command does the astronomy: it computes centerlines from CelesTrak TLEs with skyfield, picks the events worth shooting, finds the nearest point of the centerline on land, adds the Open-Meteo forecast, and renders two images per event. Your job is setup, running it, and reporting the result well.

## 1. Make sure the command exists

```bash
command -v transit-watch || uv tool install git+https://github.com/b-z/transit-watch || pipx install git+https://github.com/b-z/transit-watch
```

It needs Python 3.11+. Images need Google Chrome or Chromium; without them the report is still written.

## 2. First-time setup

If `~/.config/transit-watch/config.toml` does not exist (or `$TRANSIT_WATCH_CONFIG`), set it up before running. Ask the user, in one round of questions where possible:

- **Home location**: latitude and longitude in decimal degrees (they can right-click the spot in Google Maps and copy the numbers), elevation in meters, and IANA time zone (e.g. `Asia/Tokyo`). Never guess the location from other context without confirming it.
- **Report language**: `en`, `zh` or `ja`. Default to the language the user is writing in.
- **Thresholds**: show the defaults below and ask whether to change any. "Size" is the apparent size of the station; "distance" is how far from home the centerline may be (how far they are willing to drive).

| | min size | max distance | other |
|---|---|---|---|
| ISS × Sun | 50″ | 40 km | |
| ISS × Moon | 30″ | 160 km | Moon at least 60% lit |
| Other spacecraft × Sun | 8″ | 40 km | |
| Other spacecraft × Moon | 6″ | 160 km | Moon at least 60% lit |

For orientation: an ISS transit near the zenith is about 60″; 50″ is good; under 10″ is hardly worth it.

Then write the config without prompts, for example:

```bash
transit-watch init -y --lat 35.6812 --lon 139.7671 --elevation 5 --timezone Asia/Tokyo --language zh \
  --iss-sun-size 50 --iss-sun-km 40 --iss-moon-size 30 --iss-moon-km 160 --min-illumination 0.6
```

Other options (satellites, camera frame rate `render.fps`, output folder, model) live in the TOML file; edit it directly if the user asks.

## 3. Run and report

```bash
transit-watch run --quiet
```

The Markdown report goes to stdout and, with a JSON twin, to the output folder (`~/transit-watch/reports/` by default). Image paths are in the JSON (`events[].images`); the interactive map (`map`, one HTML file for all events) lets the user tap any point or use their phone's location to get the distance to the centerline at that point's real height. Offer its path, and mention it needs HTTPS hosting for location.

Report to the user:

1. One sentence with the conclusion first, e.g. "Sat 06:03:25.28: 56.6″ ISS lunar transit, clear sky, spot 145 km away" or "nothing worth shooting in the next two weeks".
2. The selected events, best first, 3–4 lines each: time to 0.01 s, size, the spot (Google Maps link, distance, elevation), weather verdict, and the comparison line. Put events with rain or overcast last.
3. Show the map and disk images of the best events if you can send files.
4. A short reminder: TLEs age, so re-run on the day of the event; a newer TLE can move the centerline by more than the difference between the two models.

Grades: ≥60″ excellent, ≥50″ good, ≥30″ fair (ISS only). Weather verdicts: rain or overcast → skip; partly cloudy → worth a try; clear.

## 4. Models

`strict` (default) uses IERS UT1, nutation and aberration; its Sun and Moon agree with JPL Horizons to 0.05″. `transit-finder` reproduces the conventions of transit-finder.com (its Moon lags about 69 s, which moves lunar centerlines by tens to a few hundred meters). Every event shows the other model's centerline as a comparison. Do not present either as ground truth for the user's photos; real-world accuracy is limited by the TLE.

## 5. Scheduling

If the user wants a daily report, schedule `transit-watch run --quiet` once a day (Claude desktop scheduled tasks, `/schedule`, or cron: `0 8 * * * transit-watch run --quiet`) and have each run summarize the report as in step 3.
