"""Build the offline scanner using pinned upstream Recast sources, outside game data."""
import argparse
from pathlib import Path
import shutil
import subprocess

COMMIT='6dc1667f580357e8a2154c28b7867bea7e8ad3a7'


def build(source,output,compiler=None):
    source=Path(source).resolve();output=Path(output).resolve()
    revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if revision!=COMMIT:raise ValueError('Recast source must be the pinned v1.6.0 commit '+COMMIT)
    if subprocess.check_output(['git','-C',str(source),'status','--porcelain','--','Recast'],text=True).strip():
        raise ValueError('Recast sources contain local changes')
    compiler=compiler or shutil.which('c++') or shutil.which('g++')
    if not compiler:raise ValueError('A C++17 compiler is required')
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    pending=output.with_name(output.name+'.tmp')
    if pending.exists():raise FileExistsError(pending)
    try:
        subprocess.run([compiler,'-std=c++17','-O2','-I',str(source/'Recast/Include'),
            str(Path(__file__).with_name('recast_scan.cpp')),
            *map(str,sorted((source/'Recast/Source').glob('*.cpp'))),'-o',str(pending)],check=True)
        # Refuse to publish a binary if a different builder created the target.
        import os
        os.link(pending,output)
    finally:pending.unlink(missing_ok=True)
    return output


def main():
    p=argparse.ArgumentParser(description='Build the offline, pinned Recast scanner')
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--compiler',help='GCC-compatible C++17 compiler, for example clang++ or g++')
    args=p.parse_args();print(build(args.source,args.output,args.compiler))

if __name__=='__main__':main()
