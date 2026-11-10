"""Command-line entry for the same environment check used by the APP."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.npcap_environment import assess, main


if __name__ == '__main__':
    raise SystemExit(main())
