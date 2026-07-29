import io
import tracemalloc
import zipfile
from pathlib import Path

from ingestion.dailymed.extraction import iter_spl_packages

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "dailymed"


def _real_spl_xml_bytes() -> bytes:
    return (GOLDEN_DIR / "human_rx_injection.xml").read_bytes()


def _build_nested_package(xml_bytes: bytes, *, include_junk: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as nested:
        if include_junk:
            nested.writestr("image-01.jpg", b"\xff\xd8\xff" + b"0" * 1024)
            nested.writestr("insert.pdf", b"%PDF-1.4" + b"0" * 1024)
        nested.writestr("document.xml", xml_bytes)
    return buffer.getvalue()


def _build_outer_archive(path: Path, package_count: int) -> None:
    xml_bytes = _real_spl_xml_bytes()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as outer:
        for i in range(package_count):
            nested_bytes = _build_nested_package(xml_bytes)
            outer.writestr(f"prescription/package_{i}.zip", nested_bytes)
        outer.writestr("files_added.txt", "housekeeping, not a package")


def test_iter_spl_packages_yields_only_xml_discarding_images_and_junk(tmp_path: Path) -> None:
    outer_path = tmp_path / "outer.zip"
    _build_outer_archive(outer_path, package_count=3)

    packages = list(iter_spl_packages(str(outer_path)))

    assert len(packages) == 3
    for package in packages:
        assert package.xml_bytes == _real_spl_xml_bytes()
        assert package.package_name.startswith("prescription/package_")


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_iter_spl_packages_skips_non_spl_and_empty_packages(tmp_path: Path) -> None:
    outer_path = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer_path, "w") as outer:
        # A package containing only images, no XML at all.
        outer.writestr(
            "prescription/images_only.zip", _zip_bytes({"image-01.jpg": b"not xml at all"})
        )
        # A package whose ".xml" file isn't actually an SPL document.
        outer.writestr(
            "prescription/not_spl.zip", _zip_bytes({"not_spl.xml": b"<not-spl-at-all/>"})
        )
        # One real, valid package.
        outer.writestr("prescription/valid.zip", _build_nested_package(_real_spl_xml_bytes()))

    packages = list(iter_spl_packages(str(outer_path)))

    assert len(packages) == 1
    assert packages[0].package_name == "prescription/valid.zip"


def test_iter_spl_packages_has_bounded_peak_memory(tmp_path: Path) -> None:
    """Synthetic large input: many packages, each with real SPL content plus
    junk — peak memory must stay small relative to total archive size, per
    TESTING_STRATEGY.md Section 7 (a real, required performance-characteristic
    test, not just a functional check)."""
    outer_path = tmp_path / "large_outer.zip"
    package_count = 500
    _build_outer_archive(outer_path, package_count=package_count)

    uncompressed_total = sum(
        info.file_size for info in zipfile.ZipFile(outer_path).infolist() if not info.is_dir()
    )
    assert uncompressed_total > 40 * 1024 * 1024  # sanity: a real, multi-tens-of-MB dataset

    tracemalloc.start()
    processed = 0
    for package in iter_spl_packages(str(outer_path)):
        assert package.xml_bytes  # touch it, then let it go out of scope
        processed += 1
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert processed == package_count
    # Peak traced allocation should be a small multiple of one package's size
    # (~100KB), nowhere near the ~50MB+ full uncompressed dataset.
    assert peak < 10 * 1024 * 1024, f"peak memory {peak / 1024 / 1024:.1f}MB exceeded bound"
