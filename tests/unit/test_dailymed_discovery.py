import zipfile
from pathlib import Path

from ingestion.dailymed.discovery import discover_packages, find_spl_xml_entry


def test_discover_packages_finds_only_zip_entries(tmp_path: Path) -> None:
    outer_path = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer_path, "w") as outer:
        outer.writestr("package_1.zip", b"fake nested zip bytes 1")
        outer.writestr("package_2.zip", b"fake nested zip bytes 2")
        outer.writestr("files_added.txt", "not a package")
        outer.writestr("files_deleted.txt", "")
        outer.writestr("some_dir/", "")  # directory entry

    with zipfile.ZipFile(outer_path) as outer:
        packages = discover_packages(outer)

    assert {p.name for p in packages} == {"package_1.zip", "package_2.zip"}


def test_find_spl_xml_entry_skips_images_and_pdfs(tmp_path: Path) -> None:
    nested_path = tmp_path / "package.zip"
    with zipfile.ZipFile(nested_path, "w") as nested:
        nested.writestr("image-01.jpg", b"jpeg bytes")
        nested.writestr("insert.pdf", b"pdf bytes")
        nested.writestr("95f864a3-c731-4107-9acb-efc9b740879a.xml", "<document/>")

    with zipfile.ZipFile(nested_path) as nested:
        found = find_spl_xml_entry(nested)

    assert found == "95f864a3-c731-4107-9acb-efc9b740879a.xml"


def test_find_spl_xml_entry_returns_none_when_no_xml_present(tmp_path: Path) -> None:
    nested_path = tmp_path / "package.zip"
    with zipfile.ZipFile(nested_path, "w") as nested:
        nested.writestr("image-01.jpg", b"jpeg bytes")

    with zipfile.ZipFile(nested_path) as nested:
        found = find_spl_xml_entry(nested)

    assert found is None
