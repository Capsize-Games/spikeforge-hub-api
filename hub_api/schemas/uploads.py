"""Bodies for the upload endpoints."""

from pydantic import BaseModel, Field

from hub_api.catalog import licenses, names
from hub_api.uploads import UploadRequest


class UploadIntent(BaseModel):
    """What a caller declares before sending bytes."""

    name: str = Field(max_length=64)
    version: str = Field(max_length=64)
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(gt=0)
    license: str = Field(max_length=64)
    dataset: str = Field(default="", max_length=64)
    dataset_license: str = Field(default="", max_length=64)
    dataset_attribution: str = Field(default="", max_length=2000)
    summary: str = Field(default="", max_length=200)

    def to_request(self) -> UploadRequest:
        """Return the validated internal request.

        Names and licences are checked here rather than in the route, so the
        refusal arrives before anything is reserved.
        """
        return UploadRequest(
            slug=names.validate_slug(self.name),
            version=names.validate_version(self.version),
            sha256=self.sha256.lower(),
            size_bytes=self.size_bytes,
            license=licenses.validate(self.license),
            dataset=self.dataset,
            dataset_license=(
                licenses.validate(self.dataset_license, "dataset_license")
                if self.dataset_license
                else ""
            ),
            dataset_attribution=self.dataset_attribution,
            summary=self.summary,
        )
