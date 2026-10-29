"""Synthetic source markup: never ship reader tokens or actual book pages."""
import json
import pytest
from oneshelf.plugins.native.noorbook import parse_book, page_groups, group_resources, book_url
from oneshelf.plugins.runtime import CapabilityError

HASH = 'a' * 32
TOKEN = 'b' * 40
URL = 'https://www.noor-book.com/en/ebook-test-pdf'


def work_html(*, readable=True, pages=111):
    data = {'@type': 'Book', 'name': 'White Nights', 'author': {'name': 'Dostoevsky'},
            'inLanguage': 'ar', 'numberOfPages': str(pages), 'image': '/cover.jpg'}
    return (f'<script>var book_hash = "{HASH}";</script>'
            f'<script type="application/ld+json">{json.dumps(data)}</script>'
            + ('<a class="read-btn">Read</a>' if readable else '')).encode()


def group_html(start, end, *, identity=HASH):
    return ''.join(f'<div class="page_img" page_number="{i}">'
                   + (f'<img src="/book/read_book_image/0/{identity}/{i}/{TOKEN}.svg">' if i == start else '')
                   + '</div>' for i in range(start, end + 1))


def test_metadata_uses_book_language_and_stable_hash_not_interface_language():
    book = parse_book(work_html(), URL)
    assert book.details.title == 'White Nights'
    assert book.details.language == 'ar'
    assert book.details.creator == 'Dostoevsky'
    assert book.details.cover_url == 'https://www.noor-book.com/cover.jpg'
    assert book.unit_key == 'a' * 32 + ':0'
    assert book.pages == 111 and book.readable


def test_no_read_is_recorded_and_not_mistaken_for_a_readable_book():
    assert parse_book(work_html(readable=False), URL).readable is False


@pytest.mark.parametrize('ranges,total', [([(1,100),(101,111)],111),
                                        ([(1,100),(101,200),(201,300),(301,309)],309)])
def test_all_groups_include_the_last_page_and_preserve_order(ranges, total):
    markup = ''.join(f'<a class="pages_from_to" start="{s}" end="{e}" file_num="1"></a>' for s,e in ranges)
    groups = page_groups(markup, expected_total=total)
    resources = []
    for start, end in groups:
        resources.extend(group_resources(group_html(start,end), start, end, HASH, TOKEN))
    assert len(resources) == total
    assert resources[99].page_label == '100' and resources[100].index == 100
    assert resources[-1].index == total - 1 and resources[-1].page_label == str(total)


@pytest.mark.parametrize('ranges', [[(1,100)],[(1,100),(100,111)],[(1,100),(102,111)],[(101,111),(1,100)],[(1,1101)]])
def test_partial_gapped_overlapping_reordered_or_oversized_groups_fail(ranges):
    markup = ''.join(f'<a class="pages_from_to" start="{s}" end="{e}" file_num="1"></a>' for s,e in ranges)
    with pytest.raises(CapabilityError): page_groups(markup, expected_total=111)


def test_group_from_another_book_is_rejected():
    with pytest.raises(CapabilityError):
        group_resources(group_html(101,111,identity='c'*32),101,111,HASH,TOKEN)


@pytest.mark.parametrize('body', [group_html(101,110), group_html(101,111)+group_html(111,111),
                                '<div class="page_img" page_number="101"></div>'])
def test_missing_or_duplicate_slots_cannot_yield_complete_resources(body):
    with pytest.raises(CapabilityError): group_resources(body,101,111,HASH,TOKEN)


@pytest.mark.parametrize('value', ['https://attacker.test/en/ebook-test-pdf', '//evil.test/ebook-test-pdf',
                                 '/en/ebook-test-pdf?next=bad', '/en/../private', '/en/ebook-%2Fetc-pdf'])
def test_book_input_is_not_an_arbitrary_request_url(value):
    with pytest.raises(CapabilityError): book_url(value)


def test_url_key_is_canonical_and_supports_encoded_arabic_slugs():
    assert book_url('/en/ebook-%D9%86%D9%88%D8%B1-pdf') == 'https://www.noor-book.com/en/ebook-نور-pdf'
