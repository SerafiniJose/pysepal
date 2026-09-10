"""Test the FileInput widget in pysepal.sepalwidgets.file_input."""

from pathlib import Path
from unittest.mock import MagicMock

from pysepal.sepalwidgets.file_input import FileInput


def test_select_file_accepts_path(tmp_path: Path) -> None:
    """select_file must accept a Path and store string traits.

    current_folder is a Unicode trait, so assigning a Path raised a TraitError.
    """
    csv = tmp_path / "classes.csv"
    csv.write_text("lc_class,desc,color\n1,a,#000000\n")

    file_input = FileInput(initial_folder=str(tmp_path), root=str(tmp_path))
    file_input.select_file(csv)

    assert file_input.value == str(csv)
    assert file_input.current_folder == str(tmp_path)


def test_select_file_accepts_str(tmp_path: Path) -> None:
    """select_file must also accept a plain string path (str has no .parent)."""
    csv = tmp_path / "classes.csv"
    csv.write_text("lc_class,desc,color\n1,a,#000000\n")

    file_input = FileInput(initial_folder=str(tmp_path), root=str(tmp_path))
    file_input.select_file(str(csv))

    assert file_input.value == str(csv)
    assert file_input.current_folder == str(tmp_path)


def _remote_client() -> MagicMock:
    """A SEPAL client stub whose listing is empty (get_remote_files swallows errors)."""
    client = MagicMock()
    client.files.list.return_value = MagicMock(path=".", files=[])
    return client


def test_remote_picker_prefixes_home_to_selected_value() -> None:
    """A remote picker must seed base_path with the sandbox home.

    SEPAL lists paths home-relative; the frontend prefixes ``base_path`` to the
    selected entry, so ``value`` comes back absolute like the local picker's.
    Without it consumers resolve ``downloads/x.tif`` against the CWD, which on
    SEPAL is the read-only shared app mount.
    """
    file_input = FileInput(sepal_client=_remote_client())

    assert file_input.base_path == str(Path.home())


def test_local_picker_keeps_empty_base_path(tmp_path: Path) -> None:
    """Local listings already yield absolute paths; no prefix must be added."""
    file_input = FileInput(initial_folder=str(tmp_path), root=str(tmp_path))

    assert file_input.base_path == ""


def test_explicit_base_path_is_preserved_for_remote_picker() -> None:
    """A caller-supplied base_path wins over the home default."""
    file_input = FileInput(sepal_client=_remote_client(), base_path="/custom/root")

    assert file_input.base_path == "/custom/root"
