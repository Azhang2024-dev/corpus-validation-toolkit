"""pipeline —— 编排 skill：一键跑完整链路（= run_pipeline.py）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from run_pipeline import main as pipeline_main


def main(argv=None):
    return pipeline_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
