#!/usr/bin/env python3
"""Build a privacy-scanned, self-contained candidate package."""
from pathlib import Path
import argparse,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from install import SKILLS,_build,_activate
from runtime.path_boundary import PathBoundary
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ""}
FORBIDDEN_TEXT = (
    re.compile(r"/Users/[^/\s]+/"),
    re.compile(r"\brun_[0-9a-f]{20,}\b"),
    re.compile(r"\b(?:access_token|refresh_token|app_secret)\b", re.I),
    re.compile(r"xhslink\.cn", re.I),
)


def _scan(root: Path) -> list[str]:
    failures: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in FORBIDDEN_TEXT:
            if pattern.search(text):
                failures.append(f"{path.relative_to(root)} matches {pattern.pattern}")
    return failures



def main():
    parser=argparse.ArgumentParser(description="Build a candidate only in an explicit authorized directory")
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--install-project",type=Path)
    args=parser.parse_args()
    output=PathBoundary(args.output).root
    if output.exists():raise ValueError("output exists; refusing replacement")
    _build(output)
    failures=_scan(output)
    if failures:raise ValueError("privacy scan failed: "+"; ".join(failures))
    if args.install_project:_activate(PathBoundary(args.install_project).child(".agents","skills"),output)
    print(json.dumps({"candidate":str(output),"skill_count":len(SKILLS)}))
    return 0

if __name__=="__main__":raise SystemExit(main())
