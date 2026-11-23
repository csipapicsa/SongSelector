"""Uploads the model files to their Hugging Face repos (one per model), with the model cards and licence texts.

First checks every file in --folder against the size and SHA-256 the app expects (FILES in
src/songselector/core/model_download.py), so the app can never download a file it would reject. Then makes one
commit per repo in HUGGING_FACE (same module) with the model card (packaging/models/hf/<repo>/README.md), the
licence text and the model's files, and prints each commit: put those into HUGGING_FACE, which pins the app to them.
A new repo is created private; make it public on Hugging Face once a download from it is tested.

Needs `hf auth login` with a write token (in your own terminal). Run with the project's environment:

    .venv\\Scripts\\python scripts\\publish_models.py --folder dist\\models --dry-run
    .venv\\Scripts\\python scripts\\publish_models.py --folder dist\\models
    .venv\\Scripts\\python scripts\\publish_models.py --folder dist\\models --repo csipapicsa/songselector-clap-amc
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from songselector.core.model_download import FILES, HUGGING_FACE, sha256  # noqa: E402

PACKAGING = REPO / 'packaging' / 'models'
# The licence text that must go with the files; CNN14's CC BY 4.0 needs attribution, which its model card gives.
LICENCE_TEXTS = {'csipapicsa/songselector-clap-laion': 'LICENSE-Apache-2.0.txt',
                 'csipapicsa/songselector-clap-ms': 'LICENSE-MS-PL.txt',
                 'csipapicsa/songselector-clap-amc': 'LICENSE-CC-BY-NC-SA-4.0.txt'}


def check(folder, names):
    for name in names:
        size, digest = FILES[name]
        path = folder / name
        if not path.is_file():
            sys.exit(f'Missing: {path}')
        if path.stat().st_size != size:
            sys.exit(f'{name} has {path.stat().st_size} bytes, the app expects {size}')
        if sha256(path) != digest:
            sys.exit(f'{name} does not have the SHA-256 the app expects')
        print(f'OK  {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--folder', required=True, help='folder with cnn14.onnx and the clap-* files')
    parser.add_argument('--message', default='Model files (float32 ONNX), model card, licence')
    parser.add_argument('--dry-run', action='store_true', help='only check the files; upload nothing')
    parser.add_argument('--repo', action='append', choices=sorted(HUGGING_FACE),
                        help='only this repo (repeat for several); default: all. A new model needs only its own')
    args = parser.parse_args()
    folder = Path(args.folder)
    repos = args.repo or list(HUGGING_FACE)
    check(folder, [name for repo in repos for name in HUGGING_FACE[repo][1]])
    if args.dry_run:
        print('Dry run: the files match; nothing uploaded.')
        return
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi()
    for repo in repos:
        names = HUGGING_FACE[repo][1]
        operations = [CommitOperationAdd('README.md', str(PACKAGING / 'hf' / repo.split('/')[1] / 'README.md'))]
        if repo in LICENCE_TEXTS:
            operations.append(CommitOperationAdd('LICENSE', str(PACKAGING / LICENCE_TEXTS[repo])))
        operations += [CommitOperationAdd(name, str(folder / name)) for name in names]
        api.create_repo(repo, private=True, exist_ok=True)
        commit = api.create_commit(repo, operations, commit_message=args.message)
        print(f'{repo}: {commit.oid}')
    print('Put these commits into HUGGING_FACE in src/songselector/core/model_download.py.')


if __name__ == '__main__':
    main()
