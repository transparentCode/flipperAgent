from __future__ import annotations

from hashlib import sha256

from libs.models.sr.domain.identity import canonical_json
from libs.models.sr.research.artifacts.canonical_json import (
    canonical_json_bytes,
    sha256_hex,
)


def test_canonical_json_bytes_reuses_domain_serialization_once_with_newline():
    payload = {"zero": -0.0, "nested": ["value", 1]}

    expected = (canonical_json(payload) + "\n").encode("utf-8")

    assert canonical_json_bytes(payload) == expected
    assert canonical_json_bytes(payload).endswith(b"\n")
    assert canonical_json_bytes(payload).count(b"\n") == 1


def test_sha256_hex_hashes_exact_bytes():
    data = b'{"stable":true}\n'

    assert sha256_hex(data) == sha256(data).hexdigest()
