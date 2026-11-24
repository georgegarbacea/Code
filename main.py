"""LumiBeat Studio launcher (also the PyInstaller entry point)."""
import multiprocessing
import sys

from lumibeat.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
