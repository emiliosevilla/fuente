from __future__ import annotations

import pytest

from fuente.domain.origins import (
    LegacyOriginsMigrationRequiredError,
    OriginRef,
    parse_origins,
    require_migrated_origins,
)


ORIGIN = {
    "note_id": "11111111-1111-4111-8111-111111111111",
    "revision": 2,
    "content_hash": "a" * 64,
    "path": "Tema/3_limpio/nota.md",
}


def test_parse_origins_returns_the_complete_typed_identity() -> None:
    origins = parse_origins([ORIGIN])

    assert origins == (
        OriginRef(
            note_id="11111111-1111-4111-8111-111111111111",
            revision=2,
            content_hash="a" * 64,
            path="Tema/3_limpio/nota.md",
        ),
    )


@pytest.mark.parametrize(
    "path",
    ["/Vault/3_limpio/nota.md", "../3_limpio/nota.md", "Tema\\3_limpio\\nota.md"],
)
def test_origin_ref_rejects_paths_that_are_not_vault_relative_posix(path: str) -> None:
    with pytest.raises(ValueError, match="Vault-relative POSIX path"):
        OriginRef(**{**ORIGIN, "path": path})


def test_parse_origins_rejects_partial_legacy_data_without_inventing_identity() -> None:
    with pytest.raises(ValueError, match="exactly OriginRef fields"):
        parse_origins([{"note_id": ORIGIN["note_id"], "path": ORIGIN["path"]}])


def test_parse_origins_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="exactly OriginRef fields"):
        parse_origins([{**ORIGIN, "approved": True}])


def test_origin_ref_rejects_an_invalid_note_id() -> None:
    with pytest.raises(ValueError, match="note_id"):
        OriginRef(**{**ORIGIN, "note_id": "nota-legacy"})


def test_origin_ref_rejects_an_invalid_revision() -> None:
    with pytest.raises(ValueError, match="revision"):
        OriginRef(**{**ORIGIN, "revision": 0})


def test_origin_ref_rejects_an_invalid_content_hash() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        OriginRef(**{**ORIGIN, "content_hash": "not-a-sha256"})


def test_require_migrated_origins_blocks_legacy_identifiers_with_a_clear_error() -> None:
    with pytest.raises(LegacyOriginsMigrationRequiredError, match="migrated before generation") as error:
        require_migrated_origins(("legacy-origen-42",))

    assert error.value.code == "legacy_origins_unmigrated"


def test_require_migrated_origins_allows_complete_or_empty_origin_sets() -> None:
    assert require_migrated_origins(()) is None
