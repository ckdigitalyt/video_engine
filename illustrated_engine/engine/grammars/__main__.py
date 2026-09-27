"""CLI entry: python3 -m engine.grammars list | build <GRAMMAR> <content.json>."""
import sys

from engine.grammars import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
