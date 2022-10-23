# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import multiprocessing
import os
import sys
import time

import yt_dlp

from yousable.back.download import download


def _start_process(target, *args):
    p = multiprocessing.Process(target=target, args=args)
    p.start()
    return p


def _write_json(path, data):
    with open(path + '.new', 'w') as f:
        json.dump(data, f)
    os.rename(path + '.new', path)


def monitor(config, feed):
    while True:
        def feed_pathogen(d, *r):
            return os.path.join(config['paths'][d], feed, *r)

        feed_cfg = config['feeds'][feed]
        #print(feed, feed_cfg)

        yt_dl_options = {
            'quiet': True,
            'playlist_items': f'{feed_cfg["load_entries"]}::-1'
        }
        print(f'{feed}: refreshing...')
        with yt_dlp.YoutubeDL(yt_dl_options) as ydl:
            info = ydl.extract_info(feed_cfg['url'], download=False)
        info = ydl.sanitize_info(info)
        print(f'{feed}: refreshed.')

        os.makedirs(feed_pathogen('meta'), exist_ok=True)
        _write_json(feed_pathogen('meta', 'feed.json'), info)

        for entry_info in info['entries']:
            # TODO: spawn separate live downloaders
            if 'is_live' in entry_info and entry_info['is_live']:
                print(f'SKIPPING {entry_info["title"]}: is_live=True',
                      file=sys.stderr)
                continue
            LIVE_STATUSES = ('was_live', 'not_live', 'post_live')
            live_status = entry_info.get('live_status')
            if live_status and live_status not in LIVE_STATUSES:
                print(f'SKIPPING {entry_info["title"]}: '
                      f'live_status={entry_info["live_status"]}',
                      file=sys.stderr)
                continue

            def entry_pathogen(d, *r):
                return feed_pathogen(d, entry_info['id'], *r)
            os.makedirs(entry_pathogen('meta'), exist_ok=True)
            _write_json(entry_pathogen('meta', 'entry.json'), entry_info)
            for profile in config['profiles']:
                if profile in config['feeds'][feed]['profiles']:
                    p = _start_process(download, config, feed, entry_pathogen,
                                       profile)

        time.sleep(feed_cfg['poll_seconds'])


def main(config):
    monitors = [_start_process(monitor, config, feed)
                for feed in config['feeds']]
    for p in monitors:
        p.join()
