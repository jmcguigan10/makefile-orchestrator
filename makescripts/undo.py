from __future__ import annotations

import argparse
import sys

from config_utils import apply_undo, parse_cli_bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Undo or replay the last change command.")
    parser.add_argument(
        "--action",
        default="last-change",
        help="Undo action selector. Currently supported: last-change.",
    )
    parser.add_argument(
        "--dirn",
        default="backward",
        help="Undo direction: backward or forward.",
    )
    parser.add_argument(
        "--unlog",
        default="false",
        help="Whether to remove the related log entry instead of appending a compensating entry.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action != "last-change":
            raise ValueError("Only 'make undo last-change' is supported right now.")
        message = apply_undo(args.dirn, parse_cli_bool(args.unlog))
        print(message)
        return 0
    except Exception as exc:
        print(f"undo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
