from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.adaptive_context_calibration.artifacts import (
    load_source_bundle,
    publish_source_bundle,
)


def test_source_bundle_publication_round_trips_and_rejects_tamper(tmp_path: Path, synthetic_source_bundle) -> None:
    bundle_id, path = publish_source_bundle(synthetic_source_bundle, output_root=tmp_path)
    assert bundle_id == synthetic_source_bundle.bundle_id
    loaded = load_source_bundle(path, expected_bundle_id=bundle_id)
    assert loaded.bundle_id == bundle_id
    original = (path / "TAOUSDT_12h.json").read_bytes()
    (path / "TAOUSDT_12h.json").write_bytes(original + b" ")
    with pytest.raises(ContractValidationError, match="hash mismatch"):
        load_source_bundle(path, expected_bundle_id=bundle_id)
