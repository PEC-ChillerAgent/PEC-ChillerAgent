"""Export small review logs only; keep the adapter on the server."""
import argparse
from pathlib import Path
import zipfile

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    args=p.parse_args();root=args.run_dir.resolve()
    if not root.is_dir():raise ValueError('Run directory missing')
    output=root.with_name(root.name+'_review.zip')
    # Never put model/tokenizer binaries or nested Trainer artifacts into this ZIP.
    members=sorted(f for f in root.iterdir() if f.is_file() and not f.is_symlink() and f.suffix in {'.json','.jsonl','.log','.txt'})
    if not members:raise ValueError('No review files to export')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
        for f in members:z.write(f,root.name+'/'+f.name)
    print(str(output),flush=True)

if __name__=='__main__':main()
