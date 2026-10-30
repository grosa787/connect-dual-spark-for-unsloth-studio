#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$(uname -s)" == Linux && "$(uname -m)" == aarch64 ]] || { echo 'Требуется Ubuntu ARM64 на DGX Spark.' >&2; exit 1; }
work="$(mktemp -d /tmp/connect-dual-spark-cli.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
base=https://github.com/grosa787/connect-dual-spark-for-unsloth-studio/releases/download/v0.6.0
curl -fL --retry 3 "$base/connect-dual-spark_0.6.0_arm64.deb" -o "$work/connect-dual-spark_0.6.0_arm64.deb"
curl -fL --retry 3 "$base/SHA256SUMS" -o "$work/SHA256SUMS"
(cd "$work" && grep '  connect-dual-spark_0.6.0_arm64.deb$' SHA256SUMS | sha256sum -c --strict)
sudo apt install -y "$work/connect-dual-spark_0.6.0_arm64.deb"
desktop="$(xdg-user-dir DESKTOP)"
install -m 0755 /usr/share/applications/connect-dual-spark.desktop "$desktop/Connect Dual Spark.desktop"
gio set "$desktop/Connect Dual Spark.desktop" metadata::trusted true || true
echo 'CLI установлена. Выполните connect-dual-spark install для первой настройки.'
