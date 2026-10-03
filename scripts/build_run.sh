#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_root="$(cd -- "$script_dir/.." && pwd -P)"

usage() {
    printf 'Usage: %s [version]\n' "${0##*/}"
}

fail() {
    printf 'build_run.sh: %s\n' "$1" >&2
    exit 1
}

sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        fail 'sha256sum or shasum is required'
    fi
}

if (( $# > 1 )); then
    usage >&2
    exit 2
fi
if [[ "${1:-}" == '-h' || "${1:-}" == '--help' ]]; then
    usage
    exit 0
fi

for command_name in awk cat chmod cp find grep head install mktemp python3 sed tar tail; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command not found: $command_name"
done

runtime_paths=(
    "dual_spark/fastload.py"
    "dual_spark/fastload_manager.py"
    "dual_spark/update_proxy.py"
    "dual_spark/patches/rpc-no-hash-cache.patch"
)

for source_path in \
    "$project_root/dual_spark/__init__.py" \
    "$project_root/dual_spark/cli.py" \
    "$project_root/dual_spark/language.py" \
    "$project_root/dual_spark/llama_wrapper.py" \
    "$project_root/dual_spark/fastload.py" \
    "$project_root/dual_spark/fastload_manager.py" \
    "$project_root/dual_spark/update_proxy.py" \
    "$project_root/dual_spark/patches/rpc-no-hash-cache.patch" \
    "$project_root/packaging/run-header.sh.in"; do
    [[ -f "$source_path" ]] || fail "required source file not found: $source_path"
done

if [[ -n "$(find "$project_root/dual_spark" -type l -print -quit)" ]]; then
    fail 'dual_spark must not contain symbolic links'
fi

package_version="${1:-}"
if [[ -z "$package_version" ]]; then
    package_version="$(sed -nE 's/^__version__[[:space:]]*=[[:space:]]*"([^"]+)"/\1/p' "$project_root/dual_spark/__init__.py" | head -n 1)"
fi
[[ "$package_version" =~ ^[0-9A-Za-z][0-9A-Za-z.+:~_-]*$ ]] || \
    fail 'version contains unsupported characters'

output_dir="${OUTPUT_DIR:-$project_root/dist}"
install -d -m 0755 "$output_dir"

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/connect-dual-spark-run.XXXXXXXX")"
cleanup() {
    rm -rf -- "$build_dir"
}
trap cleanup EXIT

payload_root="$build_dir/payload"
archive_path="$build_dir/payload.tar.gz"
built_run="$build_dir/Connect-Dual-Spark-arm64.run"
mkdir -m 0755 "$payload_root"
cp -R "$project_root/dual_spark" "$payload_root/dual_spark"
find "$payload_root/dual_spark" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$payload_root/dual_spark" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$payload_root/dual_spark" -type d -exec chmod 0755 {} +
find "$payload_root/dual_spark" -type f -exec chmod 0644 {} +
PYTHONPATH="$payload_root" python3 -c 'import dual_spark.cli'

COPYFILE_DISABLE=1 tar -C "$payload_root" -czf "$archive_path" dual_spark
archive_contents="$(tar -tzf "$archive_path")"
for runtime_path in "${runtime_paths[@]}"; do
    grep -Fqx -- "$runtime_path" <<<"$archive_contents" || \
        fail "required runtime file is missing from payload: $runtime_path"
done
payload_sha256="$(sha256_file "$archive_path")"

sed \
    -e "s/@PACKAGE_VERSION@/$package_version/g" \
    -e "s/@PAYLOAD_SHA256@/$payload_sha256/g" \
    "$project_root/packaging/run-header.sh.in" \
    > "$built_run"
cat "$archive_path" >> "$built_run"
chmod 0755 "$built_run"

if grep -aEq '@(PACKAGE_VERSION|PAYLOAD_SHA256)@' "$built_run"; then
    fail 'an installer template placeholder was not replaced'
fi

header_lines="$(awk '/^__CONNECT_DUAL_SPARK_PAYLOAD_BELOW__$/ { print NR; exit }' "$built_run")"
[[ -n "$header_lines" ]] || fail 'payload marker is missing from generated installer'
head -n "$header_lines" "$built_run" | bash -n

output_path="$output_dir/Connect-Dual-Spark-arm64.run"
install -m 0755 "$built_run" "$output_path"
"$output_path" --verify

printf 'Built %s\n' "$output_path"
printf 'SHA-256: %s\n' "$(sha256_file "$output_path")"
printf 'Verified %d fastload runtime files in payload\n' "${#runtime_paths[@]}"
