# Expanded tuning v2 — 30-track ja/en corpus

Winner: **stable-ts / medium**

## Summary

| method | slice | lines | <=1s | <=2s | median |
|---|---|---|---|---|---|
| stable-ts | tuning default |  | 63.96% | 68.22% | 0.51s |
| stable-ts | tuning best |  | 73.14% | 78.19% | 0.46s |
| stable-ts | comparison default |  | 57.44% | 65.98% | 0.77s |
| stable-ts | comparison best |  | 64.88% | 72.87% | 0.62s |
| whisper | tuning default |  | 61.17% | 65.43% | 0.65s |
| whisper | tuning best |  | 70.21% | 75.80% | 0.53s |
| whisper | comparison default |  | 59.23% | 65.84% | 0.76s |
| whisper | comparison best |  | 60.88% | 67.22% | 0.71s |

## stable-ts / medium

Best cfg: `{"similarity_mode": "bigram", "interpolate_fallback": true, "accept_threshold": 0.4, "window_pad": 12, "est_cjk_divisor": 2}`

### By language (comparison best)

| lang | <=1s | <=2s | median |
|---|---|---|---|
| ja | 69.89% | 79.77% | 0.55s |
| en | 57.39% | 62.54% | 0.77s |

### Per-track (comparison best)

| # | lang | track | <=1s | offset | median |
|---|---|---|---|---|---|
| 16 | ja | tayori-深夜特急 | 86.4% | 0.48s | 0.23s |
| 17 | ja | Toaka-GRAY | 70.6% | 0.35s | 0.68s |
| 18 | ja | Aimyon-Marigold | 78.7% | 0.99s | 0.50s |
| 19 | ja | ZUTOMAYO-Fig Smoke | 51.3% | 1.19s | 0.95s |
| 20 | ja | Yuika-かわいくない | 86.9% | 0.02s | 0.22s |
| 21 | ja | Centimillimental-かなわない、 | 66.7% | 0.26s | 0.38s |
| 22 | ja | エルスウェア紀行-Blue In | 87.5% | 0.46s | 0.43s |
| 23 | ja | tayori-Stargazer | 93.5% | 0.48s | 0.38s |
| 24 | ja | Superfly-花蔭 | 60.5% | 0.74s | 0.81s |
| 25 | ja | FantasticYouth-雲外憧憬 - English ver. | 35.8% | 0.15s | 6.42s |
| 26 | en | BLACKPINK-How You Like That | 67.3% | 1.75s | 0.62s |
| 27 | en | Adele-Hello | 72.9% | 0.02s | 0.33s |
| 28 | en | Bruno Mars-Uptown Funk | 41.8% | -0.41s | 2.98s |
| 29 | en | Adele-Rolling in the Deep | 45.6% | 0.20s | 3.43s |
| 30 | en | Linkin Park-Numb | 85.7% | 0.92s | 0.24s |

### Per-track (tuning best)

| # | lang | track | <=1s | offset | median |
|---|---|---|---|---|---|
| 1 | ja | YOASOBI-オリオン | 72.7% | 1.02s | 0.64s |
| 2 | ja | HACHI-透明軌道 | 80.0% | 0.46s | 0.44s |
| 3 | ja | milet-Fly High | 56.6% | 21.86s | 0.90s |
| 4 | ja | 美波-DROP | 82.0% | 1.80s | 0.43s |
| 5 | ja | Rokudenashi-Circling the Stars | 89.4% | 0.22s | 0.16s |
| 6 | ja | Yorushika-雲を抜け風下へ私だけ | 62.2% | -5.22s | 0.46s |
| 7 | ja | Daoko-打上花火 | 81.1% | -0.03s | 0.33s |
| 8 | ja | TRUE-Sincerely | 97.0% | 8.35s | 0.27s |
| 9 | ja | Eir Aoi-Walk on your way | 96.0% | 0.11s | 0.19s |
| 10 | ja | Eve-AIYOU | 92.9% | 0.48s | 0.39s |
| 11 | en | Taylor Swift-Shake It Off | 52.2% | -0.41s | 0.87s |
| 12 | en | Ed Sheeran-Shape Of You | 59.8% | -5.85s | 0.49s |
| 13 | en | BTS-Dynamite | 68.4% | 0.70s | 0.55s |
| 14 | en | Coldplay-Yellow | 78.4% | 1.38s | 0.24s |
| 15 | en | Imagine Dragons-Believer (Audio) | 70.2% | 0.52s | 0.39s |

## whisper / medium

Best cfg: `{"similarity_mode": "bigram", "interpolate_fallback": true, "accept_threshold": 0.3, "window_pad": 12, "est_cjk_divisor": 2}`

### By language (comparison best)

| lang | <=1s | <=2s | median |
|---|---|---|---|
| ja | 68.97% | 75.40% | 0.47s |
| en | 48.80% | 54.98% | 1.25s |

### Per-track (comparison best)

| # | lang | track | <=1s | offset | median |
|---|---|---|---|---|---|
| 16 | ja | tayori-深夜特急 | 93.2% | 0.23s | 0.27s |
| 17 | ja | Toaka-GRAY | 67.7% | 0.09s | 0.32s |
| 18 | ja | Aimyon-Marigold | 85.1% | 0.94s | 0.42s |
| 19 | ja | ZUTOMAYO-Fig Smoke | 59.0% | 0.99s | 0.74s |
| 20 | ja | Yuika-かわいくない | 91.8% | -0.24s | 0.34s |
| 21 | ja | Centimillimental-かなわない、 | 71.4% | 0.26s | 0.26s |
| 22 | ja | エルスウェア紀行-Blue In | 90.6% | 0.16s | 0.28s |
| 23 | ja | tayori-Stargazer | 100.0% | 0.41s | 0.31s |
| 24 | ja | Superfly-花蔭 | 60.5% | 0.42s | 0.75s |
| 25 | ja | FantasticYouth-雲外憧憬 - English ver. | 6.0% | 168.31s | 35.89s |
| 26 | en | BLACKPINK-How You Like That | 63.3% | 1.31s | 0.65s |
| 27 | en | Adele-Hello | 79.2% | -0.32s | 0.39s |
| 28 | en | Bruno Mars-Uptown Funk | 56.0% | 0.12s | 0.81s |
| 29 | en | Adele-Rolling in the Deep | 25.0% | 0.16s | 66.31s |
| 30 | en | Linkin Park-Numb | 14.3% | 85.81s | 4.04s |

### Per-track (tuning best)

| # | lang | track | <=1s | offset | median |
|---|---|---|---|---|---|
| 1 | ja | YOASOBI-オリオン | 90.9% | 0.62s | 0.34s |
| 2 | ja | HACHI-透明軌道 | 93.3% | -0.06s | 0.30s |
| 3 | ja | milet-Fly High | 50.9% | 21.11s | 0.75s |
| 4 | ja | 美波-DROP | 82.0% | 1.44s | 0.33s |
| 5 | ja | Rokudenashi-Circling the Stars | 85.1% | 0.10s | 0.22s |
| 6 | ja | Yorushika-雲を抜け風下へ私だけ | 62.2% | -5.50s | 0.73s |
| 7 | ja | Daoko-打上花火 | 86.8% | 0.29s | 0.31s |
| 8 | ja | TRUE-Sincerely | 78.8% | 8.47s | 0.38s |
| 9 | ja | Eir Aoi-Walk on your way | 92.0% | -0.04s | 0.08s |
| 10 | ja | Eve-AIYOU | 85.7% | 0.54s | 0.54s |
| 11 | en | Taylor Swift-Shake It Off | 17.4% | -0.30s | 68.09s |
| 12 | en | Ed Sheeran-Shape Of You | 76.1% | -6.15s | 0.53s |
| 13 | en | BTS-Dynamite | 52.6% | 0.78s | 0.82s |
| 14 | en | Coldplay-Yellow | 70.3% | 0.42s | 0.72s |
| 15 | en | Imagine Dragons-Believer (Audio) | 66.7% | 0.12s | 0.39s |
