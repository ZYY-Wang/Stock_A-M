from __future__ import annotations

import argparse
from pathlib import Path

from .core import Store
from .sectors import backfill_concept_history, backfill_sector_history


def main() -> None:
    parser = argparse.ArgumentParser(description="补抓行业板块历史日线")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--days", type=int, default=100)
    parser.add_argument("--type", choices=["industry", "concept", "all"], default="industry")
    args = parser.parse_args()
    frames = []
    if args.type in {"industry", "all"}:
        frames.append(backfill_sector_history(days=args.days))
    if args.type in {"concept", "all"}:
        frames.append(backfill_concept_history(days=args.days))
    import pandas as pd
    history = pd.concat(frames, ignore_index=True)
    store = Store(args.root.resolve() / "data" / "market.db")
    try:
        store.initialize()
        store.save_sector_history(history)
        store.set_metadata("sector_history_source", "同花顺")
    finally:
        store.close()
    print(f"完成：{history['code'].nunique()} 个板块，{len(history)} 条日线")


if __name__ == "__main__":
    main()
