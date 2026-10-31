#!/usr/bin/env bash
set -Eeuo pipefail
version=1.2.0
archive=""
launch=()
while (( $# )); do
    case "$1" in
        --archive) archive="$2"; shift 2 ;;
        --no-launch) launch=(--no-launch); shift ;;
        *) printf 'Неизвестный параметр: %s\n' "$1" >&2; exit 2 ;;
    esac
done
[[ "$(uname -s)" == Linux && "$(uname -m)" == aarch64 ]] || { echo 'Запустите установщик на DGX Spark с Ubuntu ARM64.' >&2; exit 1; }
work="$(mktemp -d /tmp/spark-link-install.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
if [[ -z "$archive" ]]; then
    base="https://github.com/grosa787/connect-dual-spark-for-unsloth-studio/releases/download/desktop-v$version"
    archive="$work/Spark-Link-$version-arm64.tar.gz"
    curl --fail --location --retry 3 "$base/Spark-Link-$version-arm64.tar.gz" --output "$archive"
    curl --fail --location --retry 3 "$base/SHA256SUMS" --output "$work/SHA256SUMS"
    (cd "$work" && grep "  Spark-Link-$version-arm64.tar.gz$" SHA256SUMS | sha256sum --check --strict)
else
    archive="$(realpath -- "$archive")"
    [[ -f "$archive" ]] || { echo 'Архив не найден.' >&2; exit 1; }
fi
python3 - "$archive" "$work" <<'PY'
import pathlib, sys, tarfile
root=pathlib.Path(sys.argv[2]).resolve()
with tarfile.open(sys.argv[1]) as archive:
    for item in archive.getmembers():
        path=(root/item.name).resolve()
        if not path.is_relative_to(root) or item.issym() or item.islnk():
            raise SystemExit('Недопустимый путь в архиве.')
    archive.extractall(root,filter='data')
PY
bash "$work/Spark-Link/install.sh" "${launch[@]}"
