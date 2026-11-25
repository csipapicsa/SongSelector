"""The embedding models the app can use, and where their files and caches live.

Every model is an ONNX file that takes raw mono audio, (batch, samples) at its own sample rate, and returns
"embedding", one vector per window. The CLAP models also have a text encoder, so a typed description can be
compared with the tracks (core/text_search.py). The model files are not in the repo or the exe: they are made by
scripts/export_cnn14_onnx.py and scripts/export_clap_onnx.py and go into the models folder next to the app's data.

Each model has its own cache file, so caches can be deleted one model at a time, and the CNN14 cache of earlier
versions (embeddings.sqlite) stays as it was.

No PyQt5 or songselector.config here: the analysis process imports this module.
"""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EmbeddingModel:
    id: str                 # stored with every embedding and in the settings; never change it
    name: str               # shown in menus
    description: str        # tooltip
    audio_file: str         # ONNX audio encoder, in the models folder
    sample_rate: int
    chunk_seconds: float    # one vector per window of this length; the last window is zero-padded
    dim: int
    store_file: str         # cache, next to library.sqlite
    batch_sizes: dict = field(default_factory=dict)  # windows per model call, by onnxruntime provider
    text_file: str = ''     # ONNX text encoder (CLAP only)
    tokenizer_file: str = ''
    text_length: int = 0    # fixed token count (padded with id 0), 0 for the text's own length
    text_suffix: str = ''   # appended to every query, as in training

    @property
    def chunk_samples(self):
        return int(round(self.sample_rate * self.chunk_seconds))

    @property
    def has_text(self):
        return bool(self.text_file)

    def files(self):
        return [name for name in (self.audio_file, self.text_file, self.tokenizer_file) if name]

    def missing_files(self, folder):
        return [name for name in self.files() if not (Path(folder) / name).is_file()]


CNN14 = EmbeddingModel(
    id='panns-cnn14-mAP0.431', name='CNN14',
    description='PANNs CNN14: general sound similarity, 5 s windows. The original model of the app.',
    audio_file='cnn14.onnx', sample_rate=32000, chunk_seconds=5, dim=2048, store_file='embeddings.sqlite',
    # 5 s windows, GTX 1650 Ti (4 GB): CUDA batch 16 0.58 s per 6-minute track, DirectML batch 8 0.58 s
    # (batch 16: 4.2 s), CPU the same at any batch, so 1 (a pause then takes effect sooner).
    batch_sizes={'CUDAExecutionProvider': 16, 'DmlExecutionProvider': 8, 'CPUExecutionProvider': 1})

# CLAP on the same card (docs/research/text_search_clap.md): DirectML is fastest at batch 4 (LAION 62 ms per
# window, Microsoft 55 ms; batch 8 runs out of room, 150-245 ms); the CPU takes about 105 ms at any batch size.
CLAP_BATCH_SIZES = {'CUDAExecutionProvider': 8, 'DmlExecutionProvider': 4, 'CPUExecutionProvider': 1}

LAION_CLAP = EmbeddingModel(
    id='laion-clap-htsat-unfused', name='LAION CLAP',
    description='LAION CLAP (clap-htsat-unfused): sound and text in one space, 10 s windows. '
                'Enables free-text search.',
    audio_file='clap-laion-audio.onnx', sample_rate=48000, chunk_seconds=10, dim=512,
    store_file='embeddings-laion-clap.sqlite', batch_sizes=CLAP_BATCH_SIZES,
    text_file='clap-laion-text.onnx', tokenizer_file='clap-laion-tokenizer.json')

MS_CLAP = EmbeddingModel(
    id='ms-clap-2023', name='Microsoft CLAP',
    description='Microsoft CLAP 2023: sound and text in one space, 7 s windows. Enables free-text search.',
    audio_file='clap-ms-audio.onnx', sample_rate=44100, chunk_seconds=7, dim=1024,
    store_file='embeddings-ms-clap.sqlite', batch_sizes=CLAP_BATCH_SIZES,
    text_file='clap-ms-text.onnx', tokenizer_file='clap-ms-tokenizer.json',
    text_length=77, text_suffix=' <|endoftext|>')

# MTG's music-trained CLAP (docs/research/allmusiccaps_clap.md): OMAR-RQ audio encoder on raw 24 kHz audio +
# all-mpnet-base-v2 text encoder. Better than LAION on the DJ's genre tags (mean AP 0.33 vs 0.21) and faster on
# DirectML (24 ms per window at batch 4). Files from docs/research/experiments/clap/amclap_onnx.py export, published as
# csipapicsa/songselector-clap-amc under the weights' CC BY-NC-SA 4.0 (credit to MTG, non-commercial).
AMC_CLAP = EmbeddingModel(
    id='mtg-allmusiccaps-all-layers', name='AllMusicCaps CLAP (MTG)',
    description='MTG AllMusicCaps CLAP (all_layers): trained on music with captions from album reviews, '
                '10 s windows. Enables free-text search. Non-commercial licence (CC BY-NC-SA 4.0).',
    audio_file='clap-amc-audio.onnx', sample_rate=24000, chunk_seconds=10, dim=512,
    store_file='embeddings-amc-clap.sqlite', batch_sizes=CLAP_BATCH_SIZES,
    text_file='clap-amc-text.onnx', tokenizer_file='clap-amc-tokenizer.json')

# The models the app offers (menus, Model box, Get models, analysis), in menu order: the music-trained CLAP first.
# Microsoft CLAP is not offered since 2026-11-24 (user's decision): for DJ use (genre, style) it was the weakest; its
# definition and download entry stay for a later use such as searching sound samples. Its cache file is left alone.
MODELS = {model.id: model for model in (CNN14, AMC_CLAP, LAION_CLAP)}
RETIRED_MODELS = {MS_CLAP.id: MS_CLAP}
DEFAULT_MODEL_IDS = [CNN14.id]
# The similarity model (map, closest matches, description search) until one is chosen: the first of these whose files
# are there, else CNN14 as before. MTG first (2026-11-24): it found genres best on a real DJ library.
PREFERRED_SIMILARITY_IDS = [AMC_CLAP.id, LAION_CLAP.id, CNN14.id]


def model(model_id):
    """The model with this id, offered or retired; CNN14 for an unknown id (e.g. a setting from a newer version)."""
    return MODELS.get(model_id) or RETIRED_MODELS.get(model_id, CNN14)


def store_path(data_dir, spec):
    return Path(data_dir) / spec.store_file
