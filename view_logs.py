"""Portable JSONL viewer: python3 view_logs.py PATH [--component local-proxy]."""
import argparse
import json
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--component', help='Only show records from this component')
    args = parser.parse_args()
    try:
        with open(args.path, encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError as exc:
                    raise ValueError(f'Line {number}: {exc}') from exc
                if args.component and (not isinstance(record, dict) or record.get('component') != args.component):
                    continue
                print(json.dumps(record, indent=2))
    except (OSError, ValueError) as exc:
        print(f'Cannot read log: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
