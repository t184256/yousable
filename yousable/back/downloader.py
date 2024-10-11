# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import os
import random
import sys
import time
import traceback

from yousable.back.download import download
from yousable.utils import proctitle, sleep


def shuffled(container):
    return random.sample(container, k=len(container))


def _entry_ts(feed_pathogen, feed, entry_id):
    try:
        with open(feed_pathogen('meta', entry_id, 'entry.json')) as f:
            j = json.load(f)
        assert j['id'] == entry_id
        if 'release_timestamp' in j and j['release_timestamp']:
            return j['release_timestamp']
    except Exception as ex:
        print(f'{feed} {entry_id}: ERROR {ex}', file=sys.stderr)
    try:
        return os.stat(feed_pathogen('meta', entry_id, 'first_seen')).st_mtime
    except Exception as ex:
        print(f'{feed} {entry_id}: ERROR {ex}', file=sys.stderr)
    return 0


def download_feed(config, feed_name):
    proctitle(f'downloading {feed_name}...')
    print(f'downloading {feed_name}...')

    def feed_pathogen(d, *r):
        return os.path.join(config['paths'][d], feed_name, *r)

    feed_cfg = config['feeds'][feed_name]

    # Is there metadata?

    feed_json_path = feed_pathogen('meta', 'feed.json')
    if not os.path.exists(feed_json_path):
        print(f'SKIPPING {feed_name}: no metadata', file=sys.stderr)
        return

    # Is it time to refresh already?

    refreshed_marker_file = feed_pathogen('meta', 'refreshed')
    downloaded_marker_file = feed_pathogen('meta', 'downloaded')
    if (os.path.exists(refreshed_marker_file) and
            os.path.exists(downloaded_marker_file)):
        tr = os.stat(refreshed_marker_file).st_mtime
        td = os.stat(downloaded_marker_file).st_mtime
        if td > tr:  # TODO: could be even stricter with change detection?
            print(f'skipping {feed_name}: '
                  f'no updates for {int(time.time() - tr)}s',
                  file=sys.stderr)
            return

    downloaded_marker_file_tmp = feed_pathogen('meta', 'downloaded.tmp')
    with open(downloaded_marker_file_tmp, 'w'):
        pass

    # Load metadata

    with open(feed_pathogen('meta', 'feed.json')) as f:
        feed_info = json.load(f)

    # Download stuff

    entries = feed_info['entries']
    for i, e in enumerate(shuffled(entries)):
        if e is None:
            print(f'SKIPPING {feed_name}: null entry', file=sys.stderr)
            continue

        def entry_pathogen(d, *r):
            return feed_pathogen(d, e['id'], *r)

        entry_json = entry_pathogen('meta', 'entry.json')
        if not os.path.exists(entry_json):
            print(f'skipping {feed_name} {e["id"]}: no metadata')
            continue

        if e.get('live_status') == 'is_upcoming':
            print(f'skipping {feed_name} {e["id"]}: is upcoming')
            continue

        for profile in config['profiles']:
            if profile not in feed_cfg['profiles']:
                continue

            status = f'{feed_name}@{profile}: {i}/{len(entries)} {e["id"]}'
            proctitle(f'checking {status}')
            print(f'checking {status}', file=sys.stderr)

            try:
                download(config, feed_name, entry_pathogen, profile, retries=1)
            except Exception as ex:
                proctitle(f'ERROR {status}')
                print(f'ERROR {status}', file=sys.stderr)
                traceback.print_exception(ex)
                sleep('ERROR', config=config)

    # Mark feed as processed
    os.rename(downloaded_marker_file_tmp, downloaded_marker_file)


def main(config):
    proctitle('spinning up...')
    while True:
        feeds = list(config['feeds'])
        for feed in shuffled(feeds):
            download_feed(config, feed)
            proctitle()
        sleep('just chilling', config=config)
