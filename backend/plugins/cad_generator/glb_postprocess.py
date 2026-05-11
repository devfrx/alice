"""GLB material post-processing utilities.

TRELLIS.2's texturing pipeline exports every PBR material with
``metallicFactor=1.0`` and ``roughnessFactor=1.0``, multiplied by a
predicted ``metallicRoughnessTexture``.  On stylised / anime characters
the ``metallic`` channel is unreliable and tends to saturate, so the
viewer ends up rendering the mesh as a near-pure metal under a tiny
``RoomEnvironment`` — i.e. **almost completely black**, with the real
``baseColorTexture`` ignored.

This module rewrites the JSON chunk of a binary glTF (.glb) blob in
memory, clamping ``metallicFactor`` and ``roughnessFactor`` to safer
values without touching any binary buffer (geometry, textures, UVs
remain bit-identical).

The implementation deliberately avoids pulling ``trimesh``/``pygltflib``
into the request path: the binary glTF container is trivially editable
and we want this step to be fast and side-effect free.
"""

from __future__ import annotations

import json
import struct
from typing import Any

# glTF binary container constants — see
# https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#binary-gltf-layout
_GLB_MAGIC = b"glTF"
_GLB_VERSION = 2
_CHUNK_TYPE_JSON = 0x4E4F534A  # "JSON"
_CHUNK_TYPE_BIN = 0x004E4942   # "BIN\0"
_JSON_PAD_BYTE = 0x20          # space, per spec for JSON chunk padding
_BIN_PAD_BYTE = 0x00


def patch_glb_materials(
    glb_bytes: bytes,
    *,
    metallic_factor: float | None = 0.0,
    roughness_factor: float | None = 0.85,
) -> bytes:
    """Return ``glb_bytes`` with PBR factors clamped on every material.

    Parameters
    ----------
    glb_bytes:
        Raw binary glTF payload (must start with the ``glTF`` magic).
    metallic_factor:
        New ``pbrMetallicRoughness.metallicFactor`` to apply to every
        material.  Use ``0.0`` to fully neutralise an unreliable
        metallic texture (recommended for stylised characters).  Pass
        ``None`` to leave the existing value untouched.
    roughness_factor:
        New ``pbrMetallicRoughness.roughnessFactor`` to apply to every
        material.  ``0.85`` keeps the look matte without going fully
        Lambertian.  Pass ``None`` to leave the existing value
        untouched.

    Returns
    -------
    bytes
        A new GLB blob.  If the input is not a valid binary glTF or
        contains no materials, the original bytes are returned
        unchanged.

    Notes
    -----
    Only the JSON chunk is rewritten; the binary chunk (geometry +
    textures) is reattached verbatim.  Padding rules from the glTF 2.0
    spec are preserved (JSON padded with spaces, BIN padded with zeros,
    each chunk aligned to 4 bytes).
    """
    if metallic_factor is None and roughness_factor is None:
        return glb_bytes

    if len(glb_bytes) < 12 or glb_bytes[:4] != _GLB_MAGIC:
        return glb_bytes

    version, total_length = struct.unpack_from("<II", glb_bytes, 4)
    if version != _GLB_VERSION or total_length > len(glb_bytes):
        return glb_bytes

    # --- read JSON chunk header -------------------------------------
    if len(glb_bytes) < 20:
        return glb_bytes
    json_chunk_len, json_chunk_type = struct.unpack_from("<II", glb_bytes, 12)
    if json_chunk_type != _CHUNK_TYPE_JSON:
        return glb_bytes

    json_start = 20
    json_end = json_start + json_chunk_len
    if json_end > total_length:
        return glb_bytes

    try:
        gltf: dict[str, Any] = json.loads(glb_bytes[json_start:json_end])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return glb_bytes

    materials = gltf.get("materials")
    if not isinstance(materials, list) or not materials:
        return glb_bytes

    changed = False
    for mat in materials:
        if not isinstance(mat, dict):
            continue
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        if not isinstance(pbr, dict):
            continue
        if metallic_factor is not None:
            if pbr.get("metallicFactor") != metallic_factor:
                pbr["metallicFactor"] = float(metallic_factor)
                changed = True
        if roughness_factor is not None:
            if pbr.get("roughnessFactor") != roughness_factor:
                pbr["roughnessFactor"] = float(roughness_factor)
                changed = True

    if not changed:
        return glb_bytes

    # --- rebuild the JSON chunk (4-byte aligned, space-padded) ------
    new_json = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    pad_len = (-len(new_json)) % 4
    if pad_len:
        new_json += bytes([_JSON_PAD_BYTE]) * pad_len

    # --- reattach the BIN chunk (if any) verbatim -------------------
    bin_chunk = b""
    if json_end + 8 <= total_length:
        bin_chunk_len, bin_chunk_type = struct.unpack_from("<II", glb_bytes, json_end)
        bin_end = json_end + 8 + bin_chunk_len
        if bin_chunk_type == _CHUNK_TYPE_BIN and bin_end <= total_length:
            bin_chunk = glb_bytes[json_end:bin_end]
            # BIN chunks are already 4-byte aligned per spec; keep as-is.

    new_total = 12 + 8 + len(new_json) + len(bin_chunk)
    out = bytearray()
    out += _GLB_MAGIC
    out += struct.pack("<II", _GLB_VERSION, new_total)
    out += struct.pack("<II", len(new_json), _CHUNK_TYPE_JSON)
    out += new_json
    out += bin_chunk
    return bytes(out)
