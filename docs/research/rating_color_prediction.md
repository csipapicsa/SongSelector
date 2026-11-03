# Predicting a track's rating and colour from its sound

Question (2026-11-03): about 1,300 of 3,734 library tracks have no Traktor rating, and about
1,700 no colour. Writing them by hand takes long. Can the app suggest them from the CNN14 audio
embeddings? Plan: [rating_color_plan.md](rating_color_plan.md).

## Data

`dist/library.sqlite` and `dist/embeddings.sqlite` as of 2026-11-03: 3,734 tracks, 3,617 with CNN14
embeddings (median 74 five-second windows per track).

| | Values |
|---|---|
| Traktor rating | none 1,330; 1 star 80; 2: 222; 3: 893; 4: 696; 5: 513 |
| Traktor colour | none 1,225; "0" (no colour) 429; 1: 439; **2: 1,015**; 3: 192; 4: 82; 5: 201; 6: 113; 7: 38 |
| *Rating/Color - Song Selector* (the app's own) | 1 track each: not usable as labels |

Colour 2 is on about half of the coloured tracks and the rating 3 on 37 %. Always guessing these
gives 49 % and 37 % right: that is the number any model has to beat.

## Exploratory results (2026-11-03, before the proper harness)

Leave-one-out and 5-fold on all labelled tracks, **not** grouped by artist (so, if anything,
optimistic). Accuracy = exactly right.

| Target | Always the most common | Nearest neighbours on CNN14 (k=5-20) | Logistic regression / small neural net on CNN14 | Genre tags + BPM | Same folder |
|---|---|---|---|---|---|
| Rating 1-5 | 37 % | 35-37 % | 37-39 % | 35 % | 36-38 % |
| Colour 1-7 | 49 % | 47-51 % | 51-54 % | 47 % | 50 % |

- Within one star of the right rating: 77 % for always guessing 3, the same as the sound-based guess.
- Summary choice (mean, mean+std, max over windows) and training on single 5 s windows instead
  of the track average made no difference (AUC 0.60-0.61 for rating 4-5 vs 1-3).
- With a chosen colour against the rest, colour 5 stood out: AUC 0.83, matching the tags (58 %
  of "prog" tracks are colour 5).

## Baseline with the proper validation (2026-11-03)

`experiments/rating_color/evaluate.py --model cnn14`: development artists only (80 %; 20 % of
artists are locked for the final test), 5-fold cross-validation grouped by artist, repeated 3
times; 95 % intervals by bootstrap over tracks. Results: `experiments/results/2026-11-03_cnn14.json`.

| Target (labelled tracks) | Always the most common | Nearest neighbours | Logistic regression |
|---|---|---|---|
| Rating 1-5 (1,944): balanced accuracy | 20 % | 22 % | 22 % (21-23) |
| Rating: within 1 star | 75 % | 76 % | 79 % (77-81) |
| Rating 4-5 vs 1-3: AUC | 0.50 | 0.59 | **0.61** (0.58-0.64) |
| Colour 1-7 (1,686): balanced accuracy | 14 % | 21 % | 20 % (19-21) |

Colour against the rest (logistic regression; AUC 0.5 = chance, 1 = perfect). "Top 20 %": of the
20 % of tracks the model is surest about, how many really have that colour (compare with the share).

| Colour | Share of tracks | AUC | Top 20 % right |
|---|---|---|---|
| 5 | 10 % | **0.84** (0.81-0.87) | 31 % (at most 50 % is possible) |
| 1 | 20 % | **0.79** (0.76-0.82) | 52 % |
| 4 | 4 % | 0.75 (0.70-0.81) | 10 % |
| 6 | 6 % | 0.70 (0.65-0.75) | 12 % |
| 3 | 9 % | 0.68 (0.64-0.73) | 20 % |
| 2 | 49 % | 0.64 (0.61-0.67) | 62 % |

Reading: the sound carries some signal for colours 1 and 5 (and 4), a little for rating, and
nothing that would justify filling hundreds of empty cells automatically. A correction to the
first exploratory read: it is colours 1 and 5, not only 5.

## Other information: BPM, key, usage (2026-11-03, `experiments/rating_color/metadata.py`)

Traktor's `collection.nml` holds BPM, key, loudness, bitrate, length, and how the track was *used*: play count,
last played, import date, hot cues, cues and the number of playlists it is on. Same validation as above
(development artists, grouped by artist); results in `experiments/results/2026-11-03_metadata.txt`.

| Target | Sound only (CNN14) | All of the above, no sound | Both |
|---|---|---|---|
| Rating 4-5 vs 1-3 (AUC) | 0.61 | **0.66** | **0.67** |
| ... without the usage features | 0.61 | 0.55 (BPM, key etc. alone: nothing) | 0.61 |
| Rating 1-5, balanced accuracy | 22 % | 26 % | 26 % |
| Colour 1-7, balanced accuracy | 20 % | 20 % | 23 % |
| Colour 5 against the rest (AUC) | 0.84 | 0.77 | 0.83 |

- **BPM, key, length, bitrate and loudness predict almost nothing about rating** (AUC 0.55); for colour they
  carry some signal (colour 5: 0.76, probably slower tempos) but add little on top of the sound.
- **Usage helps rating a bit** (0.61 to 0.66-0.67): played, cued and playlisted tracks are rated higher. But it is
  a trap: it measures that a track was *used*, and the tracks that still need a rating are mostly unused
  (never played: 77 % of the unlabelled tracks, against 44 % of the labelled ones; no hot cues: 80 % against 53 %).
  A model that leans on usage would put "average" on exactly the new tracks it should help with.

## What the literature says (searched 2026-11-03; no DJ-specific study found)

- Audio explains little of **personal liking**. Singing-voice liking: acoustic features barely
  explained the ratings and listeners agreed little with each other
  ([Sci. Rep. 2024](https://doaj.org/article/d35358bd403d44cb824ca932a508b512)). Preference for sad
  music: best model R² = 0.138 ([IEEE Access 2021](https://doaj.org/article/86540263b07a4d12906ca50788807966)).
- Content-based recommendation lives with "a large semantic gap" between audio and preference
  ([van den Oord et al. 2013](https://papers.nips.cc/paper/5004-deep-content-based-music-recommendation)).
  A model that is best on audio-analysis tasks is not necessarily best in a recommender
  ([pretrained audio representations in recommenders](https://arxiv.org/html/2409.09026v1)).
- Better embeddings exist: Jukebox features gave about 30 % better average results than
  tagging-trained models on tagging, genre, emotion and key
  ([Castellon et al. 2021](https://arxiv.org/abs/2107.05677v1)); MERT leads a tagging comparison
  ([MU-LLaMA](https://arxiv.org/pdf/2308.11276)) and the [MARBLE](https://arxiv.org/abs/2306.10548v3)
  benchmark. No common-protocol comparison of CNN14 against them on emotion was found.
- Window length: about 3 s windows, averaged per track, is the common choice; longer inputs do not
  reliably help ([overview](https://arxiv.org/pdf/2111.11636)). The 5 s used here is normal.
- With few labels, simple linear probes on pretrained embeddings come close to the best
  ([Ma & Lerch 2024](https://arxiv.org/pdf/2409.07730), about 20 examples per tag).
- Not found: a measurement of how consistently one person re-rates the same tracks, which sets the
  upper limit for any model. The plan measures it on this library.

## Open questions

1. How consistent are the labels? (re-rating test, step 1 of the plan)
2. Does a music-trained embedding (MusiCNN, Discogs-EffNet, OpenL3, MAEST, MERT, CLAP) separate
   colours or ratings better than CNN14? ([model_candidates.md](model_candidates.md))
3. Does anything beyond sound help: BPM, key, year, genre tags, play history?
4. If a label is predictable only for some values (colours 1 and 5), is "suggest only when sure"
   precise enough to be worth showing?
