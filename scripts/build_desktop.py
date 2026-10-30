#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = '1.0.0'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--wheels',required=True,type=Path)
    args=parser.parse_args()
    wheels=list(args.wheels.glob('*.whl'))
    if len(wheels)!=4: raise SystemExit('Download the four PySide6 6.8.3 ARM64 wheels first.')
    output=ROOT/'dist'
    output.mkdir(exist_ok=True)
    archive=output/f'Spark-Link-{VERSION}-arm64.tar.gz'
    with tempfile.TemporaryDirectory(prefix='spark-link-build-') as temporary:
        payload=Path(temporary)/'Spark-Link'
        payload.mkdir()
        for name,source in [('spark_link',ROOT/'desktop/spark_link'),('dual_spark',ROOT/'dual_spark')]:
            shutil.copytree(source,payload/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for name in ('install.py','install.sh','LICENSE','THIRD_PARTY_NOTICES.md'):
            shutil.copy2(ROOT/'desktop'/name,payload/name)
        shutil.copy2(ROOT/'LICENSE',payload/'CLI-LICENSE')
        (payload/'wheels').mkdir()
        for wheel in wheels: shutil.copy2(wheel,payload/'wheels'/wheel.name)
        with tarfile.open(archive,'w:gz',compresslevel=6) as bundle: bundle.add(payload,arcname='Spark-Link')
    run=output/f'Spark-Link-{VERSION}-arm64.run'
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    header='''#!/usr/bin/env bash
set -Eeuo pipefail
work="$(mktemp -d /tmp/spark-link-run.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
line="$(awk '/^__SPARK_LINK_ARCHIVE__$/ { print NR+1; exit }' "$0")"
tail -n +"$line" "$0" > "$work/payload.tar.gz"
echo "DIGEST  $work/payload.tar.gz" | sha256sum -c --strict
tar -xzf "$work/payload.tar.gz" -C "$work"
bash "$work/Spark-Link/install.sh" "$@"
exit
__SPARK_LINK_ARCHIVE__
'''.replace('DIGEST',digest)
    with run.open('wb') as stream:
        stream.write(header.encode())
        with archive.open('rb') as content: shutil.copyfileobj(content,stream)
    run.chmod(0o755)
    (output/'desktop').mkdir(exist_ok=True)
    (output/'desktop/SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (archive,run)))
    print(archive)
    print(run)

if __name__=='__main__': main()
