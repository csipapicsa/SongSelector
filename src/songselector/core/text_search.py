"""Free-text search: a typed description -> a CLAP text vector -> the closest tracks.

Text side of the CLAP models (core/embedding_models.py): the `tokenizers` library turns the text into token ids
and an ONNX text encoder turns them into a vector in the same space as the tracks' audio vectors. Tracks are
ranked by cosine similarity to it.

onnxruntime is only imported inside TextEncoder, which runs in its own process (ui/text_search_worker.py), for
the same reason as the analysis (core/embeddings.py): it must not load next to PyQt5. This module must therefore
not import PyQt5 or songselector.config.
"""
from pathlib import Path

import numpy as np


def tokenize(tokenizer, text, pad_to=None, suffix=''):
    """(input_ids, attention_mask) as (1, n) int64 arrays, the way the model was trained.

    suffix: appended to the text (Microsoft CLAP ends every caption with ' <|endoftext|>').
    pad_to: fixed length (Microsoft CLAP: 77, padded with id 0 and cut there); None for the text's own length.
    """
    encoding = tokenizer.encode(text + suffix)
    ids, mask = list(encoding.ids), list(encoding.attention_mask)
    if pad_to:
        ids, mask = ids[:pad_to], mask[:pad_to]
        ids += [0] * (pad_to - len(ids))
        mask += [0] * (pad_to - len(mask))
    return np.array([ids], dtype=np.int64), np.array([mask], dtype=np.int64)


def unit(matrix):
    matrix = np.asarray(matrix, dtype=np.float32)
    return matrix / np.maximum(np.linalg.norm(matrix, axis=-1, keepdims=True), 1e-9)


def clap_track_vector(windows):
    """One vector per track for text search: the average of its unit-length window vectors, unit length."""
    return unit(unit(windows).mean(axis=0))


def rank(query, keys, vectors, top=None):
    """[(key, score)] by cosine similarity, best first. vectors: (n, dim), unit length; query: (dim,)."""
    if not len(keys):
        return []
    scores = vectors @ unit(query)
    order = np.argsort(-scores)
    if top:
        order = order[:top]
    return [(keys[i], float(scores[i])) for i in order]


class TextEncoder:
    """Text -> unit vector with a CLAP model's ONNX text encoder (CPU: one query takes a few tens of ms)."""

    def __init__(self, spec, folder, threads=2):
        import onnxruntime
        from tokenizers import Tokenizer
        folder = Path(folder)
        self.spec = spec
        self.tokenizer = Tokenizer.from_file(str(folder / spec.tokenizer_file))
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(str(folder / spec.text_file), options,
                                                    providers=['CPUExecutionProvider'])

    def encode(self, text):
        ids, mask = tokenize(self.tokenizer, text, pad_to=self.spec.text_length, suffix=self.spec.text_suffix)
        return unit(self.session.run(['embedding'], {'input_ids': ids, 'attention_mask': mask})[0][0])


def run_text_encoder(folder, requests, responses, stop, encoder_factory=TextEncoder):
    """Entry point of the text search process: (request_id, model_id, text) in, (request_id, vector, error) out.

    Each model's text encoder is loaded on its first query (one to a few seconds) and kept.
    encoder_factory(spec, folder) must be picklable (a module-level class); tests pass a fake one.
    """
    import queue

    from songselector.core.embedding_models import model as model_spec
    encoders = {}
    while not stop.is_set():
        try:
            request_id, model_id, text = requests.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            if model_id not in encoders:
                encoders[model_id] = encoder_factory(model_spec(model_id), folder)
            responses.put((request_id, encoders[model_id].encode(text), None))
        except Exception as error:  # e.g. a missing or broken model file: report it, keep serving
            responses.put((request_id, None, f'{type(error).__name__}: {error}'))
