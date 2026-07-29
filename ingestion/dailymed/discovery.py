import zipfile
from dataclasses import dataclass


@dataclass(frozen=True)
class PackageEntry:
    """One nested-ZIP package discovered inside a DailyMed outer archive."""

    name: str


def discover_packages(outer_zip: zipfile.ZipFile) -> list[PackageEntry]:
    """List nested-ZIP package entries in the outer archive, without extracting.

    Non-ZIP entries — directory entries, and housekeeping files the exporter
    occasionally includes (`files_added.txt`, `files_deleted.txt`, checksums)
    — are skipped at the listing stage: per DAILYMED_INGESTION.md Section 2,
    anything that isn't a candidate package is never opened, let alone extracted.
    """
    return [
        PackageEntry(name=info.filename)
        for info in outer_zip.infolist()
        if not info.is_dir() and info.filename.lower().endswith(".zip")
    ]


def find_spl_xml_entry(nested_zip: zipfile.ZipFile) -> str | None:
    """Find the SPL XML entry within one nested package ZIP, by name pattern.

    Images, PDFs, and any other asset in the package are never even
    considered — matching is by `.xml` extension here; the stronger check
    (sniffing the SPL root element/namespace, per Section 3 point 3) happens
    once the bytes are actually read, in `extraction.py`.
    """
    xml_names = [
        info.filename
        for info in nested_zip.infolist()
        if not info.is_dir() and info.filename.lower().endswith(".xml")
    ]
    return xml_names[0] if xml_names else None
