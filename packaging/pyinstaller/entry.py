"""PyInstaller entry point.

Two problems this file works around, both specific to running a
multiprocessing.Pool-based app as a single frozen executable instead of a
real `python` interpreter:

1. `facematch_cli/__main__.py` uses a relative import (`from . import ...`),
   which only works when Python loads it as part of the `facematch_cli`
   package (`python -m facematch_cli`, or the `facematch` console script).
   PyInstaller instead runs whatever file it's pointed at as a standalone
   top-level script with no package context, so pointing it directly at
   `__main__.py` fails with "attempted relative import with no known parent
   package". Importing `facematch_cli.__main__` properly here gives its
   relative imports a real package to resolve against.

2. CPython's `multiprocessing.resource_tracker` always launches its helper
   process by re-executing `sys.executable -c "<code>"` - a real `python
   -c` invocation, regardless of the Pool's start method. In a frozen app,
   `sys.executable` IS this binary, which has no `-c` flag of its own, so
   that re-exec would otherwise crash (or worse, silently re-run the whole
   CLI with `-c` as a bogus subcommand). `multiprocessing.freeze_support()`
   only covers the Pool worker bootstrap (`--multiprocessing-fork`), not
   this `-c` convention, so it's handled explicitly here: detect it before
   any other import happens (heavy imports like facematch_cli would slow
   down every worker/tracker spawn) and just `exec()` the code, exactly
   like a real interpreter would.
"""
import sys

if len(sys.argv) >= 3 and sys.argv[1] == "-c":
    exec(sys.argv[2])
    sys.exit(0)

import multiprocessing  # noqa: E402

from facematch_cli.__main__ import main  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
