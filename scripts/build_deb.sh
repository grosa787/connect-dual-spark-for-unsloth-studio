#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_root="$(cd -- "$script_dir/.." && pwd -P)"

usage() {
    printf 'Usage: %s [version]\n' "${0##*/}"
}

if (( $# > 1 )); then
    usage >&2
    exit 2
fi
if [[ "${1:-}" == '-h' || "${1:-}" == '--help' ]]; then
    usage
    exit 0
fi

for command_name in dpkg dpkg-deb grep install python3 sed mktemp; do
    command -v "$command_name" >/dev/null 2>&1 || {
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
    }
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
    "$project_root/README.md" \
    "$project_root/README.ru.md" \
    "$project_root/LICENSE" \
    "$project_root/packaging/connect-dual-spark" \
    "$project_root/packaging/connect-dual-spark.desktop" \
    "$project_root/packaging/debian-control.in"; do
    [[ -f "$source_path" ]] || {
        printf 'Required source file not found: %s\n' "$source_path" >&2
        exit 1
    }
done

package_version="${1:-}"
if [[ -z "$package_version" ]]; then
    package_version="$(sed -nE 's/^__version__[[:space:]]*=[[:space:]]*"([^"]+)"/\1/p' "$project_root/dual_spark/__init__.py" | head -n 1)"
fi
[[ -n "$package_version" ]] || {
    printf 'Could not determine package version.\n' >&2
    exit 1
}
dpkg --validate-version "$package_version" >/dev/null

output_dir="${OUTPUT_DIR:-$project_root/dist}"
install -d -m 0755 "$output_dir"

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/connect-dual-spark.XXXXXXXX")"
cleanup() {
    rm -rf -- "$build_dir"
}
trap cleanup EXIT

package_root="$build_dir/package"
app_dir="$package_root/usr/lib/connect-dual-spark"

install -d -m 0755 \
    "$package_root/DEBIAN" \
    "$package_root/usr/bin" \
    "$app_dir" \
    "$package_root/usr/share/applications" \
    "$package_root/usr/share/doc/connect-dual-spark"

cp -R "$project_root/dual_spark" "$app_dir/dual_spark"
find "$app_dir/dual_spark" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$app_dir/dual_spark" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$app_dir/dual_spark" -type d -exec chmod 0755 {} +
find "$app_dir/dual_spark" -type f -exec chmod 0644 {} +
PYTHONPATH="$app_dir" python3 -c 'import dual_spark.cli'
for runtime_path in "${runtime_paths[@]}"; do
    [[ -f "$app_dir/$runtime_path" ]] || {
        printf 'Required runtime file was not copied: %s\n' "$runtime_path" >&2
        exit 1
    }
done

install -m 0755 \
    "$project_root/packaging/connect-dual-spark" \
    "$package_root/usr/bin/connect-dual-spark"
install -m 0644 \
    "$project_root/packaging/connect-dual-spark.desktop" \
    "$package_root/usr/share/applications/connect-dual-spark.desktop"
install -m 0644 \
    "$project_root/README.md" \
    "$package_root/usr/share/doc/connect-dual-spark/README.md"
install -m 0644 \
    "$project_root/README.ru.md" \
    "$package_root/usr/share/doc/connect-dual-spark/README.ru.md"
install -m 0644 \
    "$project_root/LICENSE" \
    "$package_root/usr/share/doc/connect-dual-spark/copyright"

sed "s/@VERSION@/$package_version/g" \
    "$project_root/packaging/debian-control.in" \
    > "$package_root/DEBIAN/control"
chmod 0644 "$package_root/DEBIAN/control"

output_path="$output_dir/connect-dual-spark_${package_version}_arm64.deb"
dpkg-deb --build --root-owner-group "$package_root" "$output_path"
dpkg-deb --info "$output_path" >/dev/null
package_contents="$(dpkg-deb --contents "$output_path")"
for runtime_path in "${runtime_paths[@]}"; do
    grep -Fq -- "./usr/lib/connect-dual-spark/$runtime_path" <<<"$package_contents" || {
        printf 'Required runtime file is missing from package: %s\n' "$runtime_path" >&2
        exit 1
    }
done

printf 'Built %s\n' "$output_path"
printf 'Verified %d fastload runtime files in package\n' "${#runtime_paths[@]}"
