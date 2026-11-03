# Sheets for your own judgement

CSV files, UTF-8 with BOM, separated by `;` (a Hungarian-locale Excel opens them as columns). Edit and
save them as CSV again (Excel: *Save as > CSV UTF-8*). Reading accepts `;` and `,`.
Scripts: `docs/research/experiments/rating_color/taste_sheets.py`.

## 1. `rerate_<date>.csv`: how consistent are you? (do this first)

60 tracks you rated before, 12 per star rating, **without** the old values (and without genre tags).

- Fill `new_rating` (1-5) and `new_colour` (1-7, or red / orange / yellow / green / blue / indigo / violet)
  from your feeling now. Do not look at Traktor. Leave a row empty to skip it.
- Colours as Traktor numbers them: 1 red, 2 orange, 3 yellow, 4 green, 5 blue, 6 indigo, 7 violet.
- Then: `python taste_sheets.py rerate-score ../../sheets/rerate_<date>.csv`
  gives how often you agree with your old self (exactly / within one star / weighted kappa).
  This is the ceiling: a model cannot be expected to agree with you more than you agree with yourself.
  Doing it over two sittings (a few days apart) makes it more reliable.

## 2. `valid_<model>_<date>.csv`: do the suggestions match your taste?

About 120 tracks that have no rating and/or colour, with the model's suggestion and how sure it is.

- `predicted_rating` / `predicted_colour` with `rating_confidence` / `colour_confidence`.
- Write `yes` or `no` in `valid_rating` / `valid_colour`: "is this what I would have set?" (only where
  there is a prediction). `similar_ratings` / `similar_colours` are the labels of the 5 most similar
  tracks you have already labelled, as a hint of why.
- `chosen_by`: `surest rating` / `surest colour` are the suggestions the model is most confident about
  (the ones the app would show); `random` are ordinary missing tracks. Both are needed to know how
  often a suggestion is right, and whether confidence means anything.
- Then: `python taste_sheets.py valid-score ../../sheets/valid_<model>_<date>.csv`.
- The sheet is made per model: `python taste_sheets.py valid-make --model <name>` for a new one.

Keep the filled sheets: they are the only real measure of "matches my taste".
