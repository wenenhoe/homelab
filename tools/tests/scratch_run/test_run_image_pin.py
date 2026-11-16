from __future__ import annotations

import pytest
from scratch_run.image_pin import PIN_FILE, ImagePin, ImagePinError, image_problems, load_pin

URL = "https://pkg.opnsense.org/releases/26.1/OPNsense-26.1.6-nano-amd64.img.bz2"
SUM = "a" * 64


def pin_file(tmp_path, text):
    path = tmp_path / "image-pin.yaml"
    path.write_text(text)
    return path


def test_the_committed_pin_is_one_a_run_accepts():
    pin = load_pin()
    assert (pin, image_problems(pin.url, pin.sha256)) == (ImagePin(pin.url, pin.sha256), [])
    assert PIN_FILE.is_file()


def test_a_pin_is_read_as_its_url_and_checksum(tmp_path):
    assert load_pin(pin_file(tmp_path, f"url: {URL}\nsha256: {SUM}\n")) == ImagePin(URL, SUM)


@pytest.mark.parametrize(
    ("url", "checksum", "fragment"),
    [
        pytest.param(URL.replace("https", "http"), SUM, "image URL", id="plain-http"),
        pytest.param(URL.replace("-nano-", "-dvd-"), SUM, "image URL", id="not-nano"),
        pytest.param(URL.removesuffix(".bz2"), SUM, "image URL", id="not-bz2"),
        pytest.param(URL, "A" * 64, "image checksum", id="uppercase"),
        pytest.param(URL, "a" * 63, "image checksum", id="short"),
    ],
)
def test_a_url_or_checksum_that_is_not_acceptable_is_named(url, checksum, fragment):
    assert any(fragment in problem for problem in image_problems(url, checksum))


def test_both_problems_are_reported_together():
    assert len(image_problems("nope", "nope")) == 2


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        pytest.param(f"url: {URL}\n", "exactly the strings", id="missing-key"),
        pytest.param(f"url: {URL}\nsha256: {SUM}\nextra: 1\n", "exactly the strings", id="extra-key"),
        pytest.param(f"url: {URL}\nsha256: 123\n", "exactly the strings", id="not-a-string"),
        pytest.param("- a\n- b\n", "exactly the strings", id="not-a-mapping"),
        pytest.param(f"url: {URL}\nurl: {URL}\nsha256: {SUM}\n", "cannot be read", id="duplicate-key"),
        pytest.param("url: [\n", "cannot be read", id="not-yaml"),
        pytest.param(f"url: http://x/a-nano.img.bz2\nsha256: {SUM}\n", "image URL", id="bad-url"),
    ],
)
def test_a_pin_file_that_is_wrong_is_refused_with_its_path(tmp_path, text, fragment):
    path = pin_file(tmp_path, text)
    with pytest.raises(ImagePinError, match=fragment) as error:
        load_pin(path)
    assert str(path) in str(error.value)


def test_a_missing_pin_file_is_refused(tmp_path):
    with pytest.raises(ImagePinError, match="cannot be read"):
        load_pin(tmp_path / "absent.yaml")
