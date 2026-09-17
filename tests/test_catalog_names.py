"""Handles, slugs, versions, and licence declarations."""

import pytest

from hub_api.catalog import licenses, names
from hub_api.errors import ConflictError


@pytest.mark.parametrize("raw", ["joe", "Joe", "a-b-c", "x1", "a" * 39])
def test_a_valid_handle_is_lower_cased(raw: str) -> None:
    assert names.normalise_handle(raw) == raw.lower()


@pytest.mark.parametrize(
    "raw", ["", "-lead", "trail-", "has space", "a" * 40, "under_score"]
)
def test_a_malformed_handle_is_refused(raw: str) -> None:
    with pytest.raises(names.InvalidNameError):
        names.normalise_handle(raw)


@pytest.mark.parametrize("raw", ["reference", "nir", "SpikeForge", "api"])
def test_a_reserved_handle_is_refused(raw: str) -> None:
    # Nothing may publish under a name that reads like a curated entry.
    with pytest.raises(ConflictError, match="reserved"):
        names.normalise_handle(raw)


def test_a_community_id_is_unambiguous_against_a_curated_one() -> None:
    assert names.entry_id("joe", "dvs-gesture") == "@joe/dvs-gesture"


@pytest.mark.parametrize("raw", ["m", "my-model", "my.model_2", "a" * 64])
def test_a_valid_slug_is_accepted(raw: str) -> None:
    assert names.validate_slug(raw) == raw


@pytest.mark.parametrize("raw", ["", ".lead", "trail-", "a" * 65, "a/b"])
def test_a_malformed_slug_is_refused(raw: str) -> None:
    with pytest.raises(names.InvalidNameError):
        names.validate_slug(raw)


@pytest.mark.parametrize("raw", ["1.0.0", "v2", "0.1.0-rc1", "2024.05+a"])
def test_a_valid_version_is_accepted(raw: str) -> None:
    assert names.validate_version(raw) == raw


@pytest.mark.parametrize("raw", ["", "-1.0", "a b", "a" * 65])
def test_a_malformed_version_is_refused(raw: str) -> None:
    with pytest.raises(names.InvalidNameError):
        names.validate_version(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "BSD-3-Clause",
        "MIT",
        "CC-BY-SA-4.0",
        "Apache-2.0",
        "GPL-2.0-or-later",
        "MIT OR Apache-2.0",
        "GPL-3.0 WITH Classpath-exception-2.0",
    ],
)
def test_an_spdx_licence_is_accepted(raw: str) -> None:
    assert licenses.validate(raw) == raw


def test_the_unverified_marker_is_accepted_verbatim() -> None:
    # Being honest about not knowing is a valid answer; guessing is not.
    assert licenses.validate("unverified-candidate") == (
        "unverified-candidate"
    )


@pytest.mark.parametrize(
    "raw", ["", "unknown", "see repo", "MIT-ish, probably", "Other", "n/a"]
)
def test_a_non_answer_is_refused(raw: str) -> None:
    with pytest.raises(licenses.InvalidLicenseError):
        licenses.validate(raw)


def test_the_refusal_names_the_field() -> None:
    with pytest.raises(licenses.InvalidLicenseError) as caught:
        licenses.validate("unknown", field="dataset_license")
    assert caught.value.extra["field"] == "dataset_license"
    assert "dataset_license" in caught.value.detail
