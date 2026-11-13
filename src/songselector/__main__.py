"""Allows `python -m songselector`."""
import sys

from songselector.app import main

# The guard matters: the embedding analysis process re-imports this module.
if __name__ == '__main__':
    sys.exit(main())
