# Getting the models

The similarity map, closest matches, groups and search by description use **audio models**: neural networks that
listen to each track and describe its sound as numbers. They're an optional, separate download.

!!! note "These are public models, not SongSelector's own"
    Each model was made and published by a research group: PANNs (Kong et al.), LAION, Microsoft and the Music
    Technology Group (MTG) in Barcelona. SongSelector only converts them so they run inside the app, and credits
    each one on its download page. None of them was trained for DJing: some learned from general sounds, some from
    music with written reviews. So **expect surprises**: a model can group tracks in ways that make no sense to you,
    and search results depend a lot on the words you use. Try several models and phrasings, and treat the results
    as suggestions, not answers.

## Download

**Analysis → Get models… → Download.** The files come from Hugging Face, resume if interrupted, and are checked
before use.

| Model | Made by | Trained on | Good for | Size | Licence |
|---|---|---|---|---|---|
| CNN14 | Kong et al. (PANNs), 2020 | General sounds (AudioSet) | Sound similarity (map, closest matches) | 327 MB | CC BY 4.0 |
| LAION CLAP | LAION, 2023 | Mostly sound effects and general audio, with captions | Similarity **and** search by description | 630 MB | Apache 2.0 |
| Microsoft CLAP | Microsoft, 2023 | General audio with captions | Similarity **and** search by description | 640 MB | MS-PL |
| AllMusicCaps CLAP | MTG, Universitat Pompeu Fabra | **Music**, with captions written from album reviews | Similarity **and** search by description | 730 MB | CC BY-NC-SA 4.0, **non-commercial** |

Not sure where to start? **AllMusicCaps CLAP** was trained on music and found genres best in our own small test. See
[its page](allmusiccaps.md) for what it is and its licence.

## Analysis

Once a model is on, SongSelector analyses your library **in the background**, at low priority, so your DJ software
stays responsive. Each track is analysed once; after that only new or changed files are.

- **Analysis → Embedding models**: which models are kept up to date, and how many tracks each has done.
- **Analysis → Analyse embeddings in background**: pause or resume.
- **Analysis → Parallel analysis**: how many tracks at once (automatic: 2 on a GPU).

### How long it takes

On Windows the analysis uses your **graphics card** (any DirectX 12 GPU, including integrated graphics); without
one it uses the CPU. For a 6-minute track on a laptop GPU (GTX 1650 Ti): CNN14 about 0.6 s, the CLAP models about
1–3 s. The CPU takes several times as long. The status bar shows which is in use: *GPU (DirectML)* or *CPU*.

!!! info "If the graphics card stops working"
    If the graphics driver resets during analysis, SongSelector finishes the run on the CPU and says so. The next
    start tries the GPU again.

## Models folder

By default the models live in `models\` next to the app's data. **Analysis → Models folder…** points the app at
another folder, for example one shared by several installations.

## Where they come from

Each model has its own page on Hugging Face naming the original authors, the paper, what was changed (only the file
format) and the licence: [CNN14](https://huggingface.co/csipapicsa/songselector-cnn14),
[LAION CLAP](https://huggingface.co/csipapicsa/songselector-clap-laion),
[Microsoft CLAP](https://huggingface.co/csipapicsa/songselector-clap-ms),
[AllMusicCaps CLAP](https://huggingface.co/csipapicsa/songselector-clap-amc).
