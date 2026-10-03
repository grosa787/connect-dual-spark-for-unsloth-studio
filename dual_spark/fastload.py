"""Stable identities and the narrow RPC source patch used by fastload."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping, Sequence


_BUILD_INFO = Path("BUILD_INFO.txt")
_PREBUILT_INFO = Path("UNSLOTH_PREBUILT_INFO.json")
_RPC_SOURCE = Path("ggml/src/ggml-rpc/ggml-rpc.cpp")
_LLAMA_SERVER = Path("build/bin/llama-server")
_RPC_LIBRARY = Path("build/bin/libggml-rpc.so")

_RPC_CACHE_FUNCTION = """static bool rpc_use_hash_cache(const ggml_tensor * tensor, size_t size) {
    return size > HASH_THRESHOLD && tensor->buffer->usage == GGML_BACKEND_BUFFER_USAGE_WEIGHTS;
}"""

_PATCHED_RPC_CACHE_FUNCTION = """static bool rpc_use_hash_cache(const ggml_tensor * tensor, size_t size) {
    if (std::getenv("GGML_RPC_NO_HASH_CACHE")) {
        static const bool logged = []() {
            GGML_LOG_INFO("Connect Dual Spark: RPC hash cache disabled by GGML_RPC_NO_HASH_CACHE\\n");
            return true;
        }();
        (void) logged;
        return false;
    }
    return size > HASH_THRESHOLD && tensor->buffer->usage == GGML_BACKEND_BUFFER_USAGE_WEIGHTS;
}"""


@dataclass(frozen=True)
class UpstreamIdentity:
    """Immutable identity of one complete installed Unsloth llama.cpp tree."""

    release_tag: str
    source_commit: str
    build_info_sha256: str
    prebuilt_info_sha256: str
    rpc_source_sha256: str
    llama_server_sha256: str
    rpc_library_sha256: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _read_stable(path: Path) -> bytes:
    try:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise ValueError(f"Missing or unreadable installed file: {path}") from exc
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or len(data) != after.st_size:
        raise ValueError(f"Installed tree changed while reading: {path}")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_commit(build_info: str) -> str:
    matches = re.findall(r"(?im)^source commit:\s*([0-9a-f]{7,64})\s*$", build_info)
    if len(matches) != 1:
        raise ValueError("BUILD_INFO.txt must contain exactly one source commit")
    return matches[0].lower()


def read_upstream_identity(root: Path) -> UpstreamIdentity:
    """Read and validate the installed metadata, source, and runtime hashes."""

    root = Path(root)
    build_info_path = root / _BUILD_INFO
    prebuilt_info_path = root / _PREBUILT_INFO
    rpc_source_path = root / _RPC_SOURCE
    llama_server_path = root / _LLAMA_SERVER
    rpc_library_path = root / _RPC_LIBRARY

    build_info_bytes = _read_stable(build_info_path)
    prebuilt_info_bytes = _read_stable(prebuilt_info_path)
    rpc_source_bytes = _read_stable(rpc_source_path)
    llama_server_bytes = _read_stable(llama_server_path)
    rpc_library_bytes = _read_stable(rpc_library_path)

    try:
        build_info = build_info_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("BUILD_INFO.txt is not valid UTF-8") from exc
    try:
        prebuilt_info = json.loads(prebuilt_info_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("UNSLOTH_PREBUILT_INFO.json is not valid JSON") from exc
    if not isinstance(prebuilt_info, dict):
        raise ValueError("UNSLOTH_PREBUILT_INFO.json must contain an object")

    release_tag = prebuilt_info.get("release_tag")
    marker_commit = prebuilt_info.get("source_commit")
    if not isinstance(release_tag, str) or not release_tag.strip():
        raise ValueError("UNSLOTH_PREBUILT_INFO.json is missing release_tag")
    if not isinstance(marker_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", marker_commit.strip()):
        raise ValueError("UNSLOTH_PREBUILT_INFO.json is missing a valid source commit")

    source_commit = _source_commit(build_info)
    if marker_commit.strip().lower() != source_commit:
        raise ValueError("Installed source commit metadata is inconsistent")

    return UpstreamIdentity(
        release_tag=release_tag.strip(),
        source_commit=source_commit,
        build_info_sha256=_sha256(build_info_bytes),
        prebuilt_info_sha256=_sha256(prebuilt_info_bytes),
        rpc_source_sha256=_sha256(rpc_source_bytes),
        llama_server_sha256=_sha256(llama_server_bytes),
        rpc_library_sha256=_sha256(rpc_library_bytes),
    )


def patch_rpc_source(text: str) -> str:
    """Add the opt in hash-cache bypass to one known upstream function."""

    if "GGML_RPC_NO_HASH_CACHE" in text or "Connect Dual Spark: RPC hash cache disabled" in text:
        raise ValueError("RPC source is already patched")
    if text.count(_RPC_CACHE_FUNCTION) != 1:
        raise ValueError("RPC source drift: expected exactly one supported rpc_use_hash_cache function")
    return text.replace(_RPC_CACHE_FUNCTION, _PATCHED_RPC_CACHE_FUNCTION, 1)


def build_id(identity: UpstreamIdentity, patch_digest: str, cmake_flags: Sequence[str]) -> str:
    """Return a deterministic content identity for one fastload build."""

    payload = {
        "upstream_identity": identity.to_dict(),
        "patch_digest": patch_digest,
        "cmake_flags": list(cmake_flags),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return _sha256(encoded)


def manifest_matches(
    manifest: Mapping[str, object],
    identity: UpstreamIdentity,
    binaries: Mapping[str, Path],
) -> bool:
    """Return whether a manifest describes this upstream tree and these files."""

    if not isinstance(manifest, Mapping):
        return False
    manifest_identity = manifest.get("upstream_identity")
    manifest_binaries = manifest.get("binaries")
    if manifest_identity != identity.to_dict() or not isinstance(manifest_binaries, Mapping):
        return False
    if set(manifest_binaries) != set(binaries):
        return False
    for name, path in binaries.items():
        expected = manifest_binaries.get(name)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            return False
        try:
            actual = _sha256(_read_stable(Path(os.fspath(path))))
        except (TypeError, ValueError):
            return False
        if actual != expected:
            return False
    return True
