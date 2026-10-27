"""Allows `python -m traktor_key_calculator`."""
import sys

from traktor_key_calculator.app import main

# The guard matters: the embedding analysis process re-imports this module.
if __name__ == '__main__':
    sys.exit(main())
