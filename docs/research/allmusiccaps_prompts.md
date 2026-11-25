# Search prompts for trying AllMusicCaps CLAP

Prompts to paste into *Analysis → Search by description...* when comparing MTG's AllMusicCaps CLAP with LAION
(see [allmusiccaps_clap.md](allmusiccaps_clap.md)). The model learned from short review-style sentences and Last.fm
tag lists, so the prompts mix both styles. Written 2026-11-22; not all of them fit the test library on purpose.

## Core genres of the library (does it split sub-styles?)

- `liquid drum and bass with soulful vocals and lush pads`
- `dark neurofunk with distorted, twisting basslines`
- `old-school jungle with chopped amen breaks and reggae bass`
- `jump-up drum and bass, bouncy and cheeky`
- `funky breakbeat with a groovy bassline and chopped drum breaks`
- `nu-skool breaks with acid squelches, early 2000s`
- `big beat with funky samples and a rock swagger`
- `psychedelic breaks with trance arpeggios`
- `robotic electro with 808 drums and vocoder`
- `progressive breaks, deep and hypnotic`

## Other dance music

- `deep house with warm chords and a smooth groove`
- `minimal techno, hypnotic and repetitive`
- `dark industrial techno, pounding and relentless`
- `acid house with a squelchy 303 line`
- `uplifting trance with euphoric build-ups`
- `UK garage with shuffled beats and chopped vocals`
- `dubstep with heavy wobble bass`
- `footwork, fast and frantic with chopped samples`
- `Detroit techno with soulful strings`
- `disco with funky strings and a four-on-the-floor beat`

## Far from the library (does it still know music?)

- `smooth jazz with saxophone and brushed drums`
- `ambient drone, slow and meditative`
- `roots reggae with a deep bass and offbeat guitar`
- `aggressive heavy metal with distorted guitars`
- `classical piano piece, gentle and romantic`
- `boom bap hip hop with dusty samples`
- `bossa nova with nylon guitar and soft vocals`
- `shoegaze with washed-out guitars`

## Mood and flow (a DJ's view, not genre)

- `warm-up music, relaxed but groovy`
- `peak-time energy, euphoric and driving`
- `late-night, dark and hypnotic`
- `melancholic and emotional, bittersweet`
- `playful and cheeky, fun party track`
- `tense and building, suspenseful`
- `sunny, uplifting, feel-good summer vibe`
- `aggressive and raw, rave energy`
- `chilled after-hours comedown`
- `cinematic and epic, big atmosphere`

## Probing the limits (expect some to fail; that is informative)

- `female vocals` vs `male vocals` vs `instrumental`
- `track with a long ambient intro`
- `170 BPM` vs `120 BPM` (CLAP models usually ignore numbers)
- `no vocals` (negation: CLAP models usually still return vocal tracks, because "vocals" is in the query)
- `90s rave` vs `modern production`
- `lo-fi, dusty and warm` vs `crisp, polished, loud`
- `live drummer` vs `drum machine`
- `piano` / `saxophone` / `acoustic guitar` (instruments are its weakest area, per the paper)

## How to read the results

- **Short vs descriptive:** try one idea both ways, e.g. `jungle` and
  `old-school jungle with chopped amen breaks and reggae bass`. On the library's genre tags the short form scored
  better for this model (mean AP 0.355 for bare tags vs 0.29-0.34 for sentences).
- **Same prompt in LAION:** the most useful comparison. LAION was stronger on electro and downtempo in the genre-tag
  test, so those are worth checking in both.
- **Out-of-collection prompts** still return the nearest tracks; the scores show how near. A low top score (around
  0.1-0.2) usually means "nothing like this here".
