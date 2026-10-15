import os.path
import posixpath
import pytest

from pip.download import PipSession
from pip.index import HTMLPage
from pip.index import PackageFinder, Link
from pip.utils import as_path_component, join_within_directory


def test_sort_locations_file_expand_dir(data):
    """
    Test that a file:// dir gets listdir run with expand_dir
    """
    finder = PackageFinder([data.find_links], [], session=PipSession())
    files, urls = finder._sort_locations([data.find_links], expand_dir=True)
    assert files and not urls, (
        "files and not urls should have been found at find-links url: %s" %
        data.find_links
    )


def test_sort_locations_file_not_find_link(data):
    """
    Test that a file:// url dir that's not a find-link, doesn't get a listdir
    run
    """
    finder = PackageFinder([], [], session=PipSession())
    files, urls = finder._sort_locations([data.index_url("empty_with_pkg")])
    assert urls and not files, "urls, but not files should have been found"


def test_sort_locations_non_existing_path():
    """
    Test that a non-existing path is ignored.
    """
    finder = PackageFinder([], [], session=PipSession())
    files, urls = finder._sort_locations(
        [os.path.join('this', 'doesnt', 'exist')])
    assert not urls and not files, "nothing should have been found"


class TestLink(object):

    def test_splitext(self):
        assert ('wheel', '.whl') == Link('http://yo/wheel.whl').splitext()

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("http://yo/wheel.whl", "wheel.whl"),
            ("http://yo/wheel", "wheel"),
            # A doubly-encoded separator must stay encoded: the path is decoded
            # exactly once, so the file name keeps its literal "%2F" instead of
            # collapsing into a "/".
            (
                "https://example.com/a%252Fb.whl",
                "a%2Fb.whl",
            ),
            (
                "http://yo/myproject-1.0%2Bfoobar.0-py2.py3-none-any.whl",
                "myproject-1.0+foobar.0-py2.py3-none-any.whl",
            ),
            # An encoded separator is decoded before the basename is taken,
            # so "../" sequences hidden behind "%2F" are stripped off.
            ("https://example.com/..%2F..%2Fevil.whl", "evil.whl"),
            ("https://example.com/a%2F..%2F..%2Fevil.whl", "evil.whl"),
            ("https://example.com/%2e%2e%2f%2e%2e%2fevil.whl", "evil.whl"),
            # A path-less URL falls back to the netloc without leaking auth.
            ("https://user:pass@example.com/", "example.com"),
            ("https://user:pass@example.com", "example.com"),
        ],
    )
    def test_filename(self, url, expected):
        assert Link(url).filename == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/a%252Fb.whl",
            "https://example.com/%252e%252e%252fb.whl",
        ],
    )
    def test_filename_decoded_once_stays_single_component(self, url):
        # The path is decoded exactly once, so an encoded separator stays
        # encoded and the file name remains a single path component rather
        # than collapsing into a "/"-separated path.
        filename = Link(url).filename
        assert not posixpath.isabs(filename)
        assert posixpath.basename(filename) == filename

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/..",
            "https://example.com/.",
            "https://example.com/foo/%2e%2e",
            "https://example.com/foo/%2E%2E/",
        ],
    )
    def test_filename_parent_reference_falls_back_to_netloc(self, url):
        # A path that is only a "." or ".." reference has no usable file name,
        # so filename falls back to the netloc rather than handing back a
        # traversal component that could escape a download directory.
        assert Link(url).filename == "example.com"

    @pytest.mark.parametrize(
        "url",
        [
            # A path-less URL whose authority looks like a traversal: the
            # netloc fallback must still reduce to a single path component.
            "http://..\\..\\..\\evil.whl",
            "http://../",
            "http://..",
            # Encoded traversal sequences in the path.
            "https://example.com/..%2F..%2Fevil.whl",
            "https://example.com/..%5C..%5Cevil.whl",
            "https://example.com/%2Fetc%2Fevil.whl",
        ],
    )
    def test_filename_is_always_a_path_component(self, url):
        # filename must never carry a separator or parent reference, so joining
        # it onto a directory can never escape that directory.
        name = Link(url).filename
        assert os.path.basename(name) == name
        assert posixpath.basename(name) == name
        assert name not in (os.curdir, os.pardir)

    def test_no_ext(self):
        assert '' == Link('http://yo/wheel').ext

    def test_ext(self):
        assert '.whl' == Link('http://yo/wheel.whl').ext

    def test_ext_fragment(self):
        assert '.whl' == Link('http://yo/wheel.whl#frag').ext

    def test_ext_query(self):
        assert '.whl' == Link('http://yo/wheel.whl?a=b').ext

    def test_is_wheel(self):
        assert Link('http://yo/wheel.whl').is_wheel

    def test_is_wheel_false(self):
        assert not Link('http://yo/not_a_wheel').is_wheel

    def test_fragments(self):
        url = 'git+https://example.com/package#egg=eggname'
        assert 'eggname' == Link(url).egg_fragment
        assert None is Link(url).subdirectory_fragment
        url = 'git+https://example.com/package#egg=eggname&subdirectory=subdir'
        assert 'eggname' == Link(url).egg_fragment
        assert 'subdir' == Link(url).subdirectory_fragment
        url = 'git+https://example.com/package#subdirectory=subdir&egg=eggname'
        assert 'eggname' == Link(url).egg_fragment
        assert 'subdir' == Link(url).subdirectory_fragment


@pytest.mark.parametrize(
    ("html", "url", "expected"),
    [
        (b"<html></html>", "https://example.com/", "https://example.com/"),
        (
            b"<html><head>"
            b"<base href=\"https://foo.example.com/\">"
            b"</head></html>",
            "https://example.com/",
            "https://foo.example.com/",
        ),
        (
            b"<html><head>"
            b"<base><base href=\"https://foo.example.com/\">"
            b"</head></html>",
            "https://example.com/",
            "https://foo.example.com/",
        ),
    ],
)
def test_base_url(html, url, expected):
    assert HTMLPage(html, url).base_url == expected


class MockLogger(object):
    def __init__(self):
        self.called = False

    def warning(self, *args, **kwargs):
        self.called = True


@pytest.mark.parametrize(
    ("location", "trusted", "expected"),
    [
        ("http://pypi.python.org/something", [], True),
        ("https://pypi.python.org/something", [], False),
        ("git+http://pypi.python.org/something", [], True),
        ("git+https://pypi.python.org/something", [], False),
        ("git+ssh://git@pypi.python.org/something", [], False),
        ("http://localhost", [], False),
        ("http://127.0.0.1", [], False),
        ("http://example.com/something/", [], True),
        ("http://example.com/something/", ["example.com"], False),
        ("http://eXample.com/something/", ["example.cOm"], False),
    ],
)
def test_secure_origin(location, trusted, expected):
    finder = PackageFinder([], [], session=[], trusted_hosts=trusted)
    logger = MockLogger()
    finder._validate_secure_origin(logger, location)
    assert logger.called == expected


@pytest.mark.parametrize(
    "name",
    [
        "wheel.whl",
        "myproject-1.0+foobar.0-py2.py3-none-any.whl",
        # A literal "%2F" is a normal file name, not a separator.
        "a%2Fb.whl",
    ],
)
def test_as_path_component_keeps_plain_name(name):
    assert as_path_component(name) == name


@pytest.mark.parametrize(
    "name",
    [
        os.path.join(os.sep, "abs", "pkg.whl"),
        os.path.join("..", "pkg.whl"),
        os.path.join("nested", "pkg.whl"),
    ],
)
def test_as_path_component_reduces_to_basename(name):
    # A name carrying directory components is reduced to its basename, so the
    # result always stays inside the directory it is later joined onto.
    assert as_path_component(name) == os.path.basename(name)


@pytest.mark.parametrize(
    "name", ["", ".", "..", "/", os.path.join("sub", "..")],
)
def test_as_path_component_rejects_empty_or_parent_reference(name):
    with pytest.raises(ValueError):
        as_path_component(name)


@pytest.mark.parametrize(
    "name",
    [
        "pkg.whl",
        # A literal "%2F" is a normal file name, not a separator.
        "a%2Fb.whl",
    ],
)
def test_join_within_directory_stays_inside(name):
    # The component is joined onto the directory as its final element, so the
    # result stays inside the directory.
    directory = os.path.join("base", "downloads")
    joined = join_within_directory(directory, as_path_component(name))
    assert joined == os.path.join(directory, name)
    assert os.path.basename(joined) == name


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/..%2F..%2Fevil.whl",
        "https://example.com/a%2F..%2F..%2Fevil.whl",
        "https://example.com/%2e%2e%2f%2e%2e%2fevil.whl",
        "https://example.com/foo/%2e%2e",
        "http://..",
    ],
)
def test_join_within_directory_link_filename_cannot_escape(url):
    # Joining a URL-derived file name onto a directory must never resolve to
    # a location outside that directory.
    directory = os.path.abspath(os.path.join("base", "downloads"))
    joined = os.path.normpath(
        join_within_directory(directory, Link(url).filename)
    )
    assert joined == directory or os.path.dirname(joined) == directory
