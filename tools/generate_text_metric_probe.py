from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from slideguard.probes.text_metrics import generate_text_metric_probe


def main() -> None:
    parser = ArgumentParser(description="生成PowerPoint文字测量对照样本")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    pptx_path, csv_path = generate_text_metric_probe(args.output_dir)
    print(pptx_path)
    print(csv_path)


if __name__ == "__main__":
    main()

