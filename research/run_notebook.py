"""Run a notebook from top to bottom and save it with its outputs, so it can be read without running it again.

    .research_cache\\venv-distill\\Scripts\\python research\\run_notebook.py research\\experiments\\distill\\space_diagnostics.ipynb

Uses the kernel named in the notebook and the notebook's own folder as the working folder (as when it is opened in
VS Code). The outputs stay on this machine: git stores notebooks without them (nbstripout filter, see README.md).
"""
import argparse
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('notebook', type=Path)
    parser.add_argument('--timeout', type=int, default=1800, help='seconds per cell')
    args = parser.parse_args()

    path = args.notebook.resolve()
    notebook = nbformat.read(path, as_version=4)
    started = time.time()
    NotebookClient(notebook, timeout=args.timeout, resources={'metadata': {'path': str(path.parent)}}).execute()
    nbformat.write(notebook, path)
    print(f'{path.name}: {len(notebook.cells)} cells run and saved with outputs in {(time.time() - started) / 60:.1f} min')


if __name__ == '__main__':
    main()
