"""`facematch` - find people, or group them, across a messy photo/video
archive.

Run from the project directory that holds (or will hold) references/,
matched/, sources.local.json etc. Every command is fully self-documenting;
run `facematch <command> --help` for its flags and examples.
"""
from __future__ import annotations

import argparse
import sys
from textwrap import dedent

from . import backfill_videos, build_references, dedupe, find, group

_SUBCOMMANDS = {
    "find": find,
    "group": group,
    "build-references": build_references,
    "dedupe": dedupe,
    "backfill-videos": backfill_videos,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="facematch",
        description="Find, or group, people across a photo/video archive using face matching.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            getting started - finding a specific person:
              facematch build-references              1. build embeddings from references/
              facematch find                           2. scan an archive and copy matches into matched/
              facematch dedupe                         3. (optional) collapse duplicate matches

            getting started - grouping everyone by person (no references needed):
              facematch group                          scan an archive and sort faces into person_NNN/ folders

            every command explains its own flags and shows examples:
              facematch find --help
              facematch find status --help
              facematch find restart --help
              facematch group --help
              facematch group status --help
              facematch group restart --help
            """),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, module in _SUBCOMMANDS.items():
        first_line = module.__doc__.strip().splitlines()[0] if module.__doc__ else ""
        sub = subparsers.add_parser(name, help=first_line)
        module.add_arguments(sub)

    args = parser.parse_args(argv)
    _SUBCOMMANDS[args.command].run(args)


if __name__ == "__main__":
    sys.exit(main())
