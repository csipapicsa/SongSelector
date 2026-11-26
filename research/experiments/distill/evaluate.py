"""Phase 1 evaluation: how close is a student to the teacher, and does it find genres as well?

Two kinds of numbers:
  fidelity    window cosine to the teacher (mean, 5th percentile), track cosine, and top-10 overlap: for each
              track, its 10 nearest tracks by teacher vectors vs by student vectors (the "closest matches" view)
  genre AP    the genre-tag test of ../clap/allmusiccaps.ipynb (labels, prompts and average precision copied from
              it unchanged): the DJ's own genre tags as labels, 27 prompts (9 labels x 3 styles), the original
              AllMusicCaps text encoder for the prompts. Track vector = mean of the unit window vectors, unit length,
              as in the app (core/text_search.clap_track_vector).

`python evaluate.py` logs the reference runs (teacher on 6 windows, LAION CLAP as the app has it) to MLflow
experiment distill-train, so students can be compared with them in one table.
"""
import re
import sys
from contextlib import closing
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import APP_DATA, DATA, connect_ro, mlflow_experiment, snapshot  # noqa: E402

from songselector.core import embeddings as app_embeddings  # noqa: E402
from songselector.core.embedding_models import AMC_CLAP, LAION_CLAP  # noqa: E402
from songselector.core.text_search import TextEncoder, clap_track_vector, unit  # noqa: E402

EXPERIMENT = 'distill-train'


# ---- Genre test, as in ../clap/allmusiccaps.ipynb ----------------------------------------------------------------

def positive_tags(genre):
    tokens = (t.strip().lower() for t in re.split(r'[,\\/;]', genre or ''))
    return [t for t in tokens if t and not t.startswith('-')]


LABELS = {  # label: (does a tag match?, prompts)
    'drum and bass': (lambda t: 'dnb' in t or 'drum' in t or 'jungle' in t,
                      ['drum and bass', 'This audio is a drum and bass song.',
                       'Fast, rolling drum and bass with deep sub-bass and sharp breakbeats.']),
    'breakbeat': (lambda t: 'break' in t,
                  ['breakbeat', 'This audio is a breakbeat song.',
                   'A funky breakbeat track with chopped drum breaks and a groovy bassline.']),
    'downtempo': (lambda t: 'down' in t,
                  ['downtempo', 'This audio is a downtempo song.',
                   'A laid-back downtempo track with slow beats and a warm, mellow atmosphere.']),
    'liquid': (lambda t: 'liquid' in t,
               ['liquid drum and bass', 'This audio is a liquid drum and bass song.',
                'Smooth, soulful liquid drum and bass with lush pads and melodic vocals.']),
    'neurofunk': (lambda t: 'neuro' in t,
                  ['neurofunk', 'This audio is a neurofunk song.',
                   'Dark, technical neurofunk with heavy distorted reese basslines.']),
    'jungle': (lambda t: 'jungle' in t,
               ['jungle', 'This audio is a jungle song.',
                'Old-school jungle with chopped amen breaks and booming reggae sub-bass.']),
    'psy': (lambda t: 'psy' in t,
            ['psychedelic breakbeat', 'This audio is a psychedelic breakbeat song.',
             'Trippy psychedelic breaks with acid squelches and hypnotic synth arpeggios.']),
    'electro': (lambda t: 'electro' in t and 'electronic' not in t,
                ['electro', 'This audio is an electro song.',
                 'Robotic electro with 808 drum machines and funky synth bass.']),
    'house': (lambda t: 'house' in t,
              ['house music', 'This audio is a house song.',
               'A four-on-the-floor house track with a steady kick and a groovy bassline.']),
}
STYLES = ['tag', 'template', 'caption']


def average_precision(relevant_in_rank_order):
    hits = np.cumsum(relevant_in_rank_order)
    return float((hits / np.arange(1, len(hits) + 1))[relevant_in_rank_order].mean())


def prompts():
    return [(name, style, prompt) for name, (_, texts) in LABELS.items() for style, prompt in zip(STYLES, texts)]


def text_vectors(spec=AMC_CLAP):
    """{prompt: unit text vector} with the app's ONNX text encoder; cached in DATA (the prompts never change)."""
    cache = DATA / f'text_{spec.id}.npz'
    if cache.is_file():
        stored = np.load(cache)
        return dict(zip(stored['prompts'], stored['vectors']))
    encoder = TextEncoder(spec, APP_DATA / 'models')
    texts = [prompt for _, _, prompt in prompts()]
    vectors = np.stack([encoder.encode(text) for text in texts])
    DATA.mkdir(parents=True, exist_ok=True)
    np.savez(cache, prompts=np.array(texts), vectors=vectors)
    return dict(zip(texts, vectors))


def genre_ap(track_vecs, genres, texts):
    """Mean AP over the prompts of labels with >= 5 tagged tracks, and the per-prompt rows.
    track_vecs: (n, dim) unit; genres: n genre strings; texts: {prompt: unit vector}. Ranks only tagged tracks."""
    tags = [positive_tags(genre) for genre in genres]
    pool = np.array([bool(t) for t in tags])
    rows = []
    for name, (match, _) in LABELS.items():
        relevant = np.array([any(match(t) for t in track_tags) for track_tags in tags])[pool]
        if relevant.sum() < 5:
            continue
        for style, prompt in zip(STYLES, LABELS[name][1]):
            order = np.argsort(-(track_vecs[pool] @ texts[prompt]))
            rows.append({'label': name, 'style': style, 'n': int(relevant.sum()), 'chance': float(relevant.mean()),
                         'ap': average_precision(relevant[order]), 'p10': float(relevant[order[:10]].mean())})
    return float(np.mean([row['ap'] for row in rows])), rows


# ---- Fidelity ----------------------------------------------------------------------------------------------------

def track_vectors(window_vecs, track_ids):
    """(tracks, dim) unit track vectors, in order of first appearance of each track id, and those ids."""
    ids, starts = np.unique(track_ids, return_index=True)
    ids = ids[np.argsort(starts)]
    return np.stack([clap_track_vector(window_vecs[track_ids == i]) for i in ids]), ids


def top_k_overlap(a, b, k=10):
    """Mean share of each track's k nearest neighbours (self excluded) that two sets of track vectors agree on."""
    def neighbours(vectors):
        sims = vectors @ vectors.T
        np.fill_diagonal(sims, -np.inf)
        return np.argpartition(-sims, k, axis=1)[:, :k]
    na, nb = neighbours(a), neighbours(b)
    return float(np.mean([len(set(x) & set(y)) / k for x, y in zip(na, nb)]))


def fidelity(student, teacher, track_ids):
    """Student vs teacher on the same windows. student, teacher: (windows, dim); track_ids: (windows,)."""
    cos = (unit(student) * unit(teacher)).sum(1)
    s_tracks, _ = track_vectors(student, track_ids)
    t_tracks, _ = track_vectors(teacher, track_ids)
    return {'window_cos_mean': float(cos.mean()), 'window_cos_p5': float(np.percentile(cos, 5)),
            'track_cos_mean': float((s_tracks * t_tracks).sum(1).mean()),
            'top10_overlap': top_k_overlap(s_tracks, t_tracks)}


# ---- Data access -------------------------------------------------------------------------------------------------

def load_split(split):
    """(rows into the caches, track id per row, manifest of the split's ok tracks) for val or test."""
    import pandas as pd
    manifest = pd.read_parquet(DATA / 'manifest.parquet')
    track = np.load(DATA / 'windows.npz')['track']
    chosen = manifest.index[(manifest.split == split) & manifest.ok].to_numpy()
    rows = np.flatnonzero(np.isin(track, chosen))
    return rows, track[rows], manifest.loc[chosen]


def genres_of(track_ids, manifest):
    _, first = np.unique(track_ids, return_index=True)
    ids = track_ids[np.sort(first)]
    return manifest.loc[ids, 'genre'].tolist()


def laion_track_vectors(path_keys):
    """{path_key: unit track vector} from the app's LAION CLAP cache (every window), read from a snapshot."""
    with closing(connect_ro(snapshot(APP_DATA / LAION_CLAP.store_file))) as connection:
        rows = connection.execute('SELECT path_key, frames, dim, data FROM embeddings WHERE error IS NULL').fetchall()
    wanted = set(path_keys)
    return {key: clap_track_vector(app_embeddings.decode(blob, frames, dim).astype(np.float32))
            for key, frames, dim, blob in rows if key in wanted}


# ---- Reference runs ------------------------------------------------------------------------------------------------

def log_references():
    """Teacher on the 6 cached windows and LAION CLAP (the app's other text model), on the test split."""
    import pandas as pd
    teacher = np.load(DATA / 'teacher.npy', mmap_mode='r')
    rows, track_ids, manifest = load_split('test')
    genres = genres_of(track_ids, manifest)
    mlflow = mlflow_experiment(EXPERIMENT)

    t_tracks, ids = track_vectors(np.asarray(teacher[rows]), track_ids)
    ap, per_prompt = genre_ap(t_tracks, genres, text_vectors(AMC_CLAP))
    with mlflow.start_run(run_name='teacher-6win', tags={'phase': '1', 'kind': 'reference'}):
        mlflow.log_params({'student': 'teacher-6win', 'test_tracks': len(ids)})
        mlflow.log_metrics({'test_genre_ap': ap, 'test_window_cos_mean': 1.0, 'test_top10_overlap': 1.0})
        mlflow.log_table(pd.DataFrame(per_prompt), 'genre_ap_test.json')
    print(f'teacher, 6 windows: genre AP {ap:.3f} on {len(ids)} test tracks')

    keys = manifest.loc[ids, 'path_key'].tolist()
    laion = laion_track_vectors(keys)
    have = [i for i, key in enumerate(keys) if key in laion]
    l_tracks = np.stack([laion[keys[i]] for i in have])
    ap_l, per_prompt_l = genre_ap(l_tracks, [genres[i] for i in have], text_vectors(LAION_CLAP))
    ap_t_same, _ = genre_ap(t_tracks[have], [genres[i] for i in have], text_vectors(AMC_CLAP))
    with mlflow.start_run(run_name='laion-clap', tags={'phase': '1', 'kind': 'reference'}):
        mlflow.log_params({'student': 'laion-clap', 'test_tracks': len(have)})
        mlflow.log_metrics({'test_genre_ap': ap_l, 'teacher_genre_ap_same_tracks': ap_t_same})
        mlflow.log_table(pd.DataFrame(per_prompt_l), 'genre_ap_test.json')
    print(f'LAION CLAP, every window: genre AP {ap_l:.3f} on {len(have)} test tracks (teacher on the same: '
          f'{ap_t_same:.3f})')


# ---- Is a student really as good as the teacher? -------------------------------------------------------------------

def paired_bootstrap(a, b, genres, texts_a, texts_b, resamples=500, seed=0):
    """Mean and 95% interval of genre AP(a) - AP(b) over bootstrap resamples of the test tracks. Paired: both sides
    see the same resample, so the noise from which tracks happen to be in the test set cancels out.
    a, b: (tracks, dim) unit vectors of the same tracks in the same order."""
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(resamples):
        index = rng.integers(0, len(a), len(a))
        chosen = [genres[i] for i in index]
        differences.append(genre_ap(a[index], chosen, texts_a)[0] - genre_ap(b[index], chosen, texts_b)[0])
    low, high = np.percentile(differences, [2.5, 97.5])
    return float(np.mean(differences)), float(low), float(high)


def student_test_tracks(run_name):
    """Test track vectors of a trained student (from WORK/trained/<run>/state_dict.pt) and their track ids."""
    import torch
    from common import WORK
    from students import STUDENTS
    from train import predict
    model = STUDENTS[run_name.rsplit('-n', 1)[0]]()
    model.load_state_dict(torch.load(WORK / 'trained' / run_name / 'state_dict.pt', weights_only=True))
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    rows, track_ids, _ = load_split('test')
    mel = np.asarray(np.load(DATA / f'mel{model.n_mels}.npy', mmap_mode='r')[rows])
    return track_vectors(predict(model.to(device), mel, device), track_ids)


def bootstrap_runs(run_names):
    """Paired bootstrap of each student against the teacher (6 windows) and LAION; logged onto the student's run."""
    teacher = np.load(DATA / 'teacher.npy', mmap_mode='r')
    rows, track_ids, manifest = load_split('test')
    genres = genres_of(track_ids, manifest)
    t_tracks, ids = track_vectors(np.asarray(teacher[rows]), track_ids)
    laion = laion_track_vectors(manifest.loc[ids, 'path_key'].tolist())
    l_tracks = np.stack([laion[key] for key in manifest.loc[ids, 'path_key']])
    amc, laion_texts = text_vectors(AMC_CLAP), text_vectors(LAION_CLAP)
    mlflow = mlflow_experiment(EXPERIMENT)
    for name in run_names:
        s_tracks, s_ids = student_test_tracks(name)
        assert (s_ids == ids).all()
        metrics = {}
        for label, other, other_texts in (('teacher', t_tracks, amc), ('laion', l_tracks, laion_texts)):
            mean, low, high = paired_bootstrap(s_tracks, other, genres, amc, other_texts)
            metrics.update({f'ap_minus_{label}': mean, f'ap_minus_{label}_ci_low': low,
                            f'ap_minus_{label}_ci_high': high})
            print(f'{name} - {label}: genre AP difference {mean:+.3f} (95% interval {low:+.3f} to {high:+.3f})')
        run = mlflow.search_runs(filter_string=f"attributes.run_name = '{name}' and attributes.status = 'FINISHED'",
                                 order_by=['attributes.start_time DESC']).iloc[0]
        client = mlflow.MlflowClient()
        for key, value in metrics.items():
            client.log_metric(run.run_id, key, value)


# ---- Free-text queries beyond genre tags ---------------------------------------------------------------------------

PROMPTS_FILE = Path(__file__).resolve().parents[2] / 'data' / 'allmusiccaps_prompts.md'
LONG_QUERIES = [   # the held-out themes of the distillation brief: long, compound descriptions
    'Hypnotic, psychedelic dance music with rolling tribal percussion and a deep, restrained bassline.',
    'Dusty old-school breakbeats, spacious dub textures, and a slightly menacing late-night atmosphere.',
    'Progressive club music with slowly evolving pads and a driving syncopated groove.',
    'Warm, hazy, euphoric music with organic percussion and little vocal presence.',
    'Sparse mechanical rhythms, dark atmospheres and an evolving rather than an aggressive energy.',
]


def query_sets():
    """{section: [prompt]} from research/data/allmusiccaps_prompts.md (every `quoted` prompt under a ## heading),
    plus the brief's long queries."""
    sections, current = {}, None
    for line in PROMPTS_FILE.read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            current = line[3:].split('(')[0].strip()
            if current.startswith('How to read'):   # examples repeated from the sections above
                current = None
        elif line.startswith('- ') and current:
            sections.setdefault(current, []).extend(re.findall(r'`([^`]+)`', line))
    sections['Long descriptions (brief)'] = LONG_QUERIES
    return sections


def ranking_agreement(scores_a, scores_b, ks=(10, 50)):
    """How alike two rankings of the same tracks are: top-k overlap and Spearman correlation of the scores."""
    from scipy.stats import spearmanr
    out = {f'top{k}': len(set(np.argsort(-scores_a)[:k]) & set(np.argsort(-scores_b)[:k])) / k for k in ks}
    out['spearman'] = float(spearmanr(scores_a, scores_b).statistic)
    return out


def query_agreement(run_names, out_path=None):
    """Per query: the teacher's ranking of the test tracks vs each student's (same text vector), and vs LAION's
    (its own text encoder) as a yardstick for how much two different good models agree."""
    import pandas as pd
    teacher = np.load(DATA / 'teacher.npy', mmap_mode='r')
    rows, track_ids, manifest = load_split('test')
    t_tracks, ids = track_vectors(np.asarray(teacher[rows]), track_ids)
    laion = laion_track_vectors(manifest.loc[ids, 'path_key'].tolist())
    l_tracks = np.stack([laion[key] for key in manifest.loc[ids, 'path_key']])
    students = {name: student_test_tracks(name)[0] for name in run_names}
    amc, laion_encoder = TextEncoder(AMC_CLAP, APP_DATA / 'models'), TextEncoder(LAION_CLAP, APP_DATA / 'models')
    records = []
    for section, texts in query_sets().items():
        for text in texts:
            q_amc, q_laion = amc.encode(text), laion_encoder.encode(text)
            t_scores = t_tracks @ q_amc
            models = {name: vectors @ q_amc for name, vectors in students.items()}
            models['laion-clap'] = l_tracks @ q_laion
            for model, scores in models.items():
                records.append({'section': section, 'query': text, 'model': model,
                                **ranking_agreement(t_scores, scores)})
    table = pd.DataFrame(records)
    summary = table.groupby(['section', 'model'], sort=False)[['top10', 'top50', 'spearman']].mean()
    print(summary.round(3).unstack('model').to_string())
    print('\nall queries:\n' + table.groupby('model')[['top10', 'top50', 'spearman']].mean().round(3).to_string())
    print(f'chance top-10 overlap: {10 / len(ids):.3f}')
    if out_path:
        import json
        from datetime import date
        Path(out_path).write_text(json.dumps({
            'date': str(date.today()),
            'question': 'Free-text queries beyond genre tags: how alike are the rankings of the test tracks by the '
                        'teacher (6 windows) and by each student / by LAION CLAP?',
            'tracks': len(ids), 'queries': int(table['query'].nunique()), 'chance_top10': 10 / len(ids),
            'by_section': {f'{s} | {m}': v for (s, m), v in summary.round(4).to_dict('index').items()},
            'per_query': table.round(4).to_dict('records'),
        }, indent=1), encoding='utf-8')
        print(f'Wrote {out_path}')
    return table


QUESTIONS = {
    '1': 'Phase 1 of the AllMusicCaps distillation: how close do students trained on cached log-mels get to the '
         'teacher (fidelity, genre-tag search on the test split)?',
    '2': 'Phase 2 of the AllMusicCaps distillation, first steps: with a validation set that shares no artist with the '
         'test set, can the student overfit a few tracks (is the pipeline sound), how much does longer training give, '
         'and how large is the seed-to-seed noise?',
}


def export_json(path, phase=None):
    """The latest finished run of each name in distill-train (only those tagged with `phase`, if given), as a small
    JSON for the repo (the MLflow store itself is local and git-ignored)."""
    import json
    from datetime import date
    mlflow = mlflow_experiment(EXPERIMENT)
    runs = mlflow.search_runs(filter_string="attributes.status = 'FINISHED'", order_by=['attributes.start_time DESC'])
    if phase:
        runs = runs[runs['tags.phase'] == phase]
    runs = runs.drop_duplicates('tags.mlflow.runName')
    meta = json.loads((DATA / 'meta.json').read_text(encoding='utf-8'))
    out = {'date': str(date.today()),
           'question': QUESTIONS.get(phase or '1'),
           'data': {key: meta[key] for key in ('tracks', 'windows', 'splits', 'train_windows_per_track',
                                               'eval_windows_per_track', 'frontend', 'resplit') if key in meta},
           'runs': []}
    for _, run in runs.iterrows():
        row = {'run': run['tags.mlflow.runName'], 'kind': run.get('tags.kind')}
        row.update({key[7:]: value for key, value in run.items() if key.startswith('params.') and pd_notna(value)})
        row.update({key[8:]: round(float(value), 4) for key, value in run.items()
                    if key.startswith('metrics.') and pd_notna(value)})
        out['runs'].append(row)
    Path(path).write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(f'Wrote {path} ({len(out["runs"])} runs)')


def pd_notna(value):
    import pandas as pd
    return not (value is None or (not isinstance(value, str) and pd.isna(value)))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Reference runs, a paired bootstrap of trained students, or an export.')
    parser.add_argument('--bootstrap', nargs='+', metavar='RUN', help='e.g. cnn4-small-64-n1500 cnn4-64-n1500')
    parser.add_argument('--export-json', type=Path, metavar='PATH', help='write the latest runs to a results JSON')
    parser.add_argument('--phase', help="with --export-json: only runs tagged with this phase, e.g. '2'")
    parser.add_argument('--queries', nargs='+', metavar='RUN', help='ranking agreement with the teacher per query')
    parser.add_argument('--queries-out', type=Path, metavar='PATH', help='JSON for --queries')
    arguments = parser.parse_args()
    if arguments.queries:
        query_agreement(arguments.queries, arguments.queries_out)
    elif arguments.bootstrap:
        bootstrap_runs(arguments.bootstrap)
    elif arguments.export_json:
        export_json(arguments.export_json, arguments.phase)
    else:
        log_references()
