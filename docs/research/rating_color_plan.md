# Research plan: suggest missing ratings and colours from sound

Status 2026-11-03: step 0 done; step 1 sheet made (docs/research/sheets/), waiting for the user; step 2 done on 800 tracks: no small model beats CNN14; step 3 on hold; step 4 (BPM, key, usage) done. Findings so far: [rating_color_prediction.md](rating_color_prediction.md).

## Goal and the decision it serves

Decide whether the app should suggest ratings or colours for tracks that have none, and with which
model. The answer may be "no". The bar is set **before** looking at results:

> Ship a suggestion for a value only if, on tracks of artists the model never saw, the 20 % of
> tracks it is surest about are right at least **75 %** of the time, for a value that covers at
> least **10 %** of the library. Otherwise show nothing for that value.

For scale (CNN14 baseline): colour 1 is right 52 % in its top 20 % (it is 20 % of the library),
colour 5 31 %. Ratings are far from it.

## Validation rules (why the numbers can be trusted)

1. **Artist-grouped splits.** Tracks of one artist (remixes, same album) are alike and often rated
   alike, so they never sit on both sides of a split. Tracks without an artist tag are grouped by folder.
2. **Locked test set.** 20 % of the artists (chosen by a hash of the name, so fixed) are never used
   while choosing models or settings. `evaluate.py --final` looks at them **once**, for the chosen
   setup. This guards against picking the lucky one of many tries.
3. **Repeats and intervals.** 5-fold cross-validation repeated 3 times on the other 80 %; 95 %
   intervals by bootstrap over tracks. A difference counts only if the intervals clearly separate.
4. **Right baselines.** Always the most common value, and the CNN14 vectors the app has now.
   Imbalance is handled by balanced accuracy, macro-F1 and one-colour-against-the-rest AUC, not
   plain accuracy.
5. **Simple probes.** Nearest neighbours and a logistic regression on a 100-dimension PCA, fitted
   inside each fold. With about 2,000 labels a bigger head only memorises; the embedding is what
   is being compared, so every model gets the same probe.
6. **One vector per track for every model**, so the comparison is fair: mean and standard
   deviation over the model's own windows (also tried: mean only).
7. Everything runs on a **copy** of the data, and every run writes its numbers to
   `experiments/results/<date>_<model>.json`.

## Steps

0. **Harness and CNN14 baseline.** Done: `experiments/rating_color/evaluate.py`, result 2026-11-03.
1. **How consistent are the labels?** (sheet: `sheets/rerate_<date>.csv`, `taste_sheets.py rerate-make/rerate-score`.) Export about 60 labelled tracks (stratified by rating and
   colour) as a blind sheet, re-rate them without seeing the old values, compute agreement
   (weighted kappa; share exactly equal). This is the ceiling for any model. If agreement is
   low, stop expecting a model to do better and use the time on easier tools (bulk set by group).
2. **Small, fast models first** (MusiCNN, OpenL3, Discogs-EffNet): download into `.research_cache/models/`,
   write the front end, check the output against the model's own example, then extract. Screen on a
   subset of about 600 labelled tracks, the same tracks for every model. Keep a model for step 3 if
   its colour or rating AUC beats CNN14's interval, or if it matches CNN14 at a fraction of the cost.
3. **Larger models on the survivors' terms** (MAEST, MERT-95M, CLAP music): same screening subset
   first (extraction time on this GPU is *to measure*), then all labelled tracks for the ones that
   pass.
4. **Settings of the best one or two:** window length where the model allows it (3 s, 5 s, 10 s),
   mean vs mean+std, adding BPM, key and genre tags as extra inputs (is there more than sound?).
5. **Cost:** time per track, vector size, integration work (see [model_candidates.md](model_candidates.md)).
6. **Decision.** Apply the bar above once on the locked artists. Write the outcome here, whatever it is.

## Stop rules

- Step 1 shows the labels disagree with themselves about as much as the models disagree with them:
  stop, the problem is the labels.
- After step 3 no model clears the bar on the development artists: stop, do not touch the locked set.

## What the app would do if it passes

Suggestions are kept apart from real values, drawn as an outline in the same Rating/Color cell, off by
default, with one-click accept into the *Song Selector* columns; search and sort ignore them (design
discussed 2026-11-03, not built).

## How to run

```
cd docs/research/experiments/rating_color
python evaluate.py --model cnn14          # development artists, writes results/<date>_cnn14.json
python evaluate.py --model <name>         # reads .research_cache/vectors/<name>.npz (keys + matrix)
python evaluate.py --model <name> --final # once, at the end
```
