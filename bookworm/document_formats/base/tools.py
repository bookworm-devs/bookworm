# coding: utf-8

"""Contains generic utility functions for working with documents."""

import regex as re
from io import StringIO
from bookworm.utils import NEWLINE, search
from .elements import SearchResult


def export_to_plain_text(doc, target_filename, channel):
    """This function runs in a separate process."""
    total = len(doc)
    out = StringIO()
    if out.write(doc.metadata.title or ""):
        out.write(f"{NEWLINE}{'-' * 30}{NEWLINE}")
    for n in range(total):
        if channel.is_cancellation_requested():
            out.close()
            doc.close()
            channel.cancel()
            return
        text = doc.get_page_content(n)
        out.write(f"{text}{NEWLINE}\f{NEWLINE}")
        channel.push(n)
    full_text = out.getvalue()
    with open(target_filename, "w", encoding="utf8") as file:
        file.write(full_text)
    out.close()
    doc.close()
    channel.done()


def search_book(doc, request, channel):
    """This function also runs in a separate process."""
    pattern = _make_search_re_pattern(request)
    for n in range(request.from_page, request.to_page + 1):
        resultset = []
        sect = doc[n].section.title
        for pos, snip in search(pattern, doc.get_page_content(n)):
            resultset.append(
                SearchResult(excerpt=snip, page=n, position=pos, section=sect)
            )
        channel.push(resultset)
    doc.close()
    channel.done()


def search_single_page_document(text, request, channel):
    pattern = _make_search_re_pattern(request)
    start_pos, stop_pos = request.text_range
    for pos, snip in search(pattern, text):
        actual_text_pos = start_pos + pos
        channel.push(
            [
                SearchResult(
                    excerpt=snip, page=0, position=actual_text_pos, section=""
                ),
            ]
        )
    channel.done()


def _make_search_re_pattern(request):
    I = re.I if not request.case_sensitive else 0
    if request.is_regex:
        term = request.term
        term = fr"({term})"
    else:
        term = re.escape(request.term, literal_spaces=True)
        term = fr"({term})"
        if request.whole_word:
            term = fr"\b{term}\b"
    return re.compile(term, I | re.M)
