import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

from ingestion.dailymed.discovery import discover_packages, find_spl_xml_entry

SPL_NAMESPACE = b"urn:hl7-org:v3"


@dataclass(frozen=True)
class SplPackage:
    package_name: str
    xml_bytes: bytes


def _looks_like_spl(xml_bytes: bytes) -> bool:
    """Cheap sniff for the SPL root element/namespace, without a full parse.

    The "stronger check" from DAILYMED_INGESTION.md Section 3 point 3 — the
    `.xml` extension alone (checked in discovery.py) isn't proof of content.
    """
    head = xml_bytes[:2048]
    return b"<document" in head and SPL_NAMESPACE in head


def iter_spl_packages(outer_zip_path: str) -> Iterator[SplPackage]:
    """Stream SPL XML documents out of a DailyMed outer bulk archive.

    At any point, at most one nested ZIP's bytes plus one XML document are
    held in memory — nothing from a processed package lingers past its own
    iteration (DAILYMED_INGESTION.md Section 4). The outer archive's central
    directory is read once (cheap); each nested ZIP's bytes are read into an
    in-memory buffer one at a time (safe — real packages run tens of KB to a
    few MB, per Section 4's own reasoning), never the whole outer archive.
    """
    with zipfile.ZipFile(outer_zip_path) as outer:
        for package in discover_packages(outer):
            nested_bytes = outer.read(package.name)
            with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
                xml_name = find_spl_xml_entry(nested)
                if xml_name is None:
                    continue
                xml_bytes = nested.read(xml_name)

            if not _looks_like_spl(xml_bytes):
                continue

            yield SplPackage(package_name=package.name, xml_bytes=xml_bytes)
