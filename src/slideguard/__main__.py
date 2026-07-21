from __future__ import annotations

import sys

from slideguard.app import run
from slideguard.runtime import validate_runtime


def main() -> None:
    if "--self-test" in sys.argv[1:]:
        validate_runtime()
        return
    run()


if __name__ == "__main__":
    main()
