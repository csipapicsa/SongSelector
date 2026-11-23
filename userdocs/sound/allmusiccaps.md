# AllMusicCaps CLAP (MTG)

!!! abstract "Made by MTG, not by SongSelector"
    AllMusicCaps CLAP was created by the **[Music Technology Group (MTG)](https://www.upf.edu/web/mtg)** at
    Universitat Pompeu Fabra, Barcelona. The original model is
    [mtg-upf/allmusiccaps_all_layers](https://huggingface.co/mtg-upf/allmusiccaps_all_layers). SongSelector only
    converted it to a format the app can run (ONNX) and publishes that conversion as
    [csipapicsa/songselector-clap-amc](https://huggingface.co/csipapicsa/songselector-clap-amc). All credit for the
    model and its training goes to MTG. SongSelector is not affiliated with or endorsed by MTG.

## What it is

A **CLAP** model (Contrastive Language-Audio Pretraining): it puts sounds and words in the same space, so a typed
description can find tracks that sound like it. Unlike the other CLAP models in the app, it was trained **on music**:

- **Audio side:** MTG's OMAR-RQ encoder, which first learned from 330,000 hours of music on its own and was then
  trained to match music with text.
- **Text side:** the widely used `all-mpnet-base-v2` sentence model.
- **Training pairs:** about 540,000 tracks paired with descriptions written from AllMusic album reviews: style, mood,
  tempo, energy, instrumentation, production.

That's why it understands music words ("rolling bassline", "breakbeat", "downtempo") better than models trained
mostly on sound effects.

## How well does it work?

In one small test on a real DJ library (990 tracks, 27 genre prompts, written before seeing any results), it found
tagged genres clearly better than LAION CLAP: average precision 0.33 vs 0.21. It's also faster on the GPU. That's
one DJ's library and genre tags, **not a benchmark**: your music and your words may give different results. Details
in the [research note](https://github.com/csipapicsa/SongSelector/blob/main/docs/research/allmusiccaps_clap.md).

!!! tip "Experiment"
    It was trained on album-review language, not DJ language. Describe the sound the way a music reviewer would
    (*"a laid-back downtempo track with slow beats and a warm, mellow atmosphere"*), and compare with the other CLAP
    models when a search misses.

## Licence: non-commercial

MTG released the weights under **[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)**, and the
converted files carry the same licence:

- **BY:** credit MTG (done on the download page and here).
- **NC:** **non-commercial use only.** Using it to organise your own music library is fine; selling it, or a
  product built on it, is not.
- **SA:** adaptations must be shared under the same licence.

SongSelector itself is free and GPL-3.0; the model is a separate, optional download with its own licence. It's off
until you download it.

## Get it

**Analysis → Get models…**, tick *AllMusicCaps CLAP (MTG)*, **Download**. Then choose it in the **Model** box next
to *Describe a sound*. See [Getting the models](models.md).

## Sources

- Model card: [mtg-upf/allmusiccaps_all_layers](https://huggingface.co/mtg-upf/allmusiccaps_all_layers)
- Code: [MTG/allmusiccaps](https://github.com/MTG/allmusiccaps)
- OMAR-RQ audio encoder: [arXiv:2507.03482](https://arxiv.org/abs/2507.03482)
- The conversion SongSelector downloads: [csipapicsa/songselector-clap-amc](https://huggingface.co/csipapicsa/songselector-clap-amc)
