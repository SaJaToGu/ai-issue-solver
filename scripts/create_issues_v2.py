#!/usr/bin/env python3
"""
Deprecated compatibility entrypoint.

The old v2 script created real GitHub issues immediately and used a hard-coded
GitHub user. Keep this file as a safe pointer so existing notes or shell history
do not accidentally post issues.
"""

import sys


def main() -> int:
    print("create_issues_v2.py is deprecated.")
    print("Use first: python scripts/create_issues.py --report reports/analysis.json --dry-run")
    print("Create real issues only with: python scripts/create_issues.py --report reports/analysis.json --confirm-create")
    return 1


if __name__ == "__main__":
    sys.exit(main())
