# SPDX-FileCopyrightText: 2024 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import datetime
import time

import feedparser


def timestamp(struct):
    return datetime.datetime.fromtimestamp(time.mktime(struct))


def _timestamps_of(entry):
    if 'published' in entry:
        yield timestamp(entry.published_parsed)
    if 'updated' in entry:
        yield timestamp(entry.updated_parsed)


def _timestamps_of_feed(f):
    yield from _timestamps_of(f.feed)
    for entry in f.entries:
        yield from _timestamps_of(entry)


def latest_timestamp_of_feeds(urls):
    return max(max(_timestamps_of_feed(feedparser.parse(url))) for url in urls)
