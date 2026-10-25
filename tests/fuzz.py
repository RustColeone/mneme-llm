"""The long fuzz: many seeds of random operations on a file, checking every rule of the file as it goes.

    python3 -m tests.fuzz                 # 60 seeds × 400 operations (a few minutes)
    python3 -m tests.fuzz 300 400 1000    # seeds, operations per seed, first seed

The operations are those of the stress tests (`tests.test_stress.act`); after every 100, `tests.invariants.check`
must find nothing. It prints each seed that breaks a rule or raises, and exits 1 if any did.
"""

import os
import random
import sys
import tempfile
import traceback

from tests.invariants import check
from tests.test_stress import act, open_memory


def main(seeds: int = 60, steps: int = 400, first: int = 0) -> int:
    bad = 0
    for seed in range(first, first + seeds):
        m = open_memory(os.path.join(tempfile.mkdtemp(), "fuzz.db"))
        rng = random.Random(seed)
        try:
            for step in range(steps):
                act(m, rng)
                if step % 100 == 99:
                    problems = check(m.store)
                    if problems:
                        print(f"seed {seed}, step {step}: {problems[:3]}")
                        bad += 1
                        break
        except Exception:
            print(f"seed {seed} raised:")
            traceback.print_exc(limit=4)
            bad += 1
        finally:
            m.close()
    print(f"{bad} of {seeds} seeds broke a rule")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*[int(value) for value in sys.argv[1:4]]))
