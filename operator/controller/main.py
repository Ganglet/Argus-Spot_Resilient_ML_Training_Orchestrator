"""
Argus Operator entrypoint.

Usage:
    python -m controller.main               # run operator
    kopf run controller/handlers.py         # alternative (kopf CLI)
"""

import logging
import sys

import kopf

# kopf discovers handlers by import — importing handlers registers them
import controller.handlers  # noqa: F401


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stdout,
    )
    kopf.run(clusterwide=True)


if __name__ == "__main__":
    main()
