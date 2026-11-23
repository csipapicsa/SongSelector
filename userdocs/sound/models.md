# Getting the models

The similarity map, closest matches, groups and search by description use **audio models**: neural networks that
listen to each track and describe its sound as numbers. They are an optional, separate download.

## Download

**Analysis → Get models… → Download.** The files come from Hugging Face (up to 1.6 GB for all three), resume if
interrupted, and are checked before use.

| Model | Good for | Size |
|---|---|---|
| CNN14 | Sound similarity (map, closest matches) | 327 MB |
| LAION CLAP | Similarity **and** search by description | 630 MB |
| Microsoft CLAP | Similarity **and** search by description | 640 MB |

Not sure? Start with one CLAP model: it does both.

## Analysis

Once a model is on, SongSelector analyses your library **in the background**, at low priority, so your DJ software
stays responsive. Each track is analysed once; afterwards only new or changed files are.

- **Analysis → Embedding models**: which models are kept up to date, and how many tracks each has done.
- **Analysis → Analyse embeddings in background**: pause or resume.
- **Analysis → Parallel analysis**: how many tracks at once (automatic: 2 on a GPU).

### How long it takes

On Windows the analysis uses your **graphics card** (any DirectX 12 GPU, including integrated graphics); without
one it uses the CPU. For a 6-minute track on a laptop GPU (GTX 1650 Ti): CNN14 about 0.6 s, the CLAP models about
2–3 s. The CPU takes several times that. The status bar shows which is in use: *GPU (DirectML)* or *CPU*.

!!! info "If the graphics card stops working"
    If the graphics driver resets during analysis, SongSelector finishes the run on the CPU and says so. The next
    start tries the GPU again.

## Models folder

By default the models live in `models\` next to the app's data. **Analysis → Models folder…** points the app at
another folder, for example one shared by several installations.
