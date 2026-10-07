"""Backwards-compatible entry point.

The application itself now lives in the ``inaturalist_harvestor``
package; run it with ``python -m inaturalist_harvestor``.
"""

from inaturalist_harvestor.cli import main

if __name__ == "__main__":
    main()
