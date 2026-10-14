"""Freeze the test splits: ``python -m ml.freeze`` writes ml/data/frozen.json (committed to git)."""

from ml.common import freeze

if __name__ == "__main__":
    result = freeze()
    for split, info in result["splits"].items():
        print(f"{split:12s} n={info['n']:4d} digest={info['digest'][:16]}")
