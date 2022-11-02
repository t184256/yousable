# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import datetime
import glob
import json
import multiprocessing
import os
import pytz
import random
import shutil
import sys
import time

import yt_dlp

from yousable.back.download import download
from yousable.back.live_video import live_video
from yousable.back.live_audio import live_audio


def _start_process(target, *args):
    p = multiprocessing.Process(target=target, args=args)
    p.start()
    return p


def _write_json(path, data):
    with open(path + '.new', 'w') as f:
        json.dump(data, f)
    os.rename(path + '.new', path)


def _live_enabled(lg, config, profile):
    if not config['paths']['live']:
        print(f'{lg}: skipping, live path unset', file=sys.stderr)
        return False
    if config['profiles'][profile]['live'] is None:
        print(f'{lg}: skipping, profile has no live preset', file=sys.stderr)
        return False
    return True


def _download_enabled(lg, config, profile):
    if config['profiles'][profile]['download'] is None:
        return False
    return True


def monitor(config, feed):
    while True:
        def feed_pathogen(d, *r):
            return os.path.join(config['paths'][d], feed, *r)

        feed_cfg = config['feeds'][feed]
        #print(feed, feed_cfg)

        yt_dl_options = {
            'quiet': True,
            #'verbose': True,
            'match_filter': yt_dlp.utils.match_filter_func(
                'live_status != is_upcoming'
            ),
            'playlist_items': f'{feed_cfg["load_entries"]}::-1'
        }
        print(f'{feed}: refreshing...')
        try:
            with yt_dlp.YoutubeDL(yt_dl_options) as ydl:
                info = ydl.extract_info(feed_cfg['url'], download=False)
            info = ydl.sanitize_info(info)
        except Exception as ex:
            print(f'{feed}: ERROR {ex}', file=sys.stderr)
            time.sleep(feed_cfg['poll_seconds'] / 4)
            continue
        if feed_cfg['extra_urls']:
            for extra_url in feed_cfg['extra_urls']:
                print(f'{feed}: extra url check {extra_url}...')
                try:
                    with yt_dlp.YoutubeDL(yt_dl_options) as ydl:
                        ee = ydl.extract_info(extra_url, download=False)
                    ee = ydl.sanitize_info(ee)
                    if ee and 'entries' in ee:
                        for eee in ee['entries']:
                            if eee not in info['entries']:
                                info['entries'].append(eee)
                    elif ee and ee['id'] not in info['entries']:
                        info['entries'].append(ee)
                except Exception as ex:
                    print(f'{feed}: ERROR {ex} {extra_url}', file=sys.stderr)
        print(f'{feed}: refreshed.')

        os.makedirs(feed_pathogen('meta'), exist_ok=True)
        _write_json(feed_pathogen('meta', 'feed.json'), info)

        now = datetime.datetime.now(datetime.timezone.utc)
        max_age = datetime.timedelta(seconds=feed_cfg['keep_entries_seconds'])
        max_age += datetime.timedelta(days=1)  # upload_date coarseness
        for entry_info in info['entries']:
            if 'upload_date' in entry_info and entry_info['upload_date']:
                udts = datetime.datetime.strptime(entry_info['upload_date'],
                                                  '%Y%m%d')
                if now - pytz.utc.fromutc(udts) > max_age:
                    continue  # too old
            def entry_pathogen(d, *r):
                return feed_pathogen(d, entry_info['id'], *r)
            os.makedirs(entry_pathogen('meta'), exist_ok=True)
            _write_json(entry_pathogen('meta', 'entry.json'), entry_info)
            if not os.path.exists(entry_pathogen('meta', 'first_seen')):
                with open(entry_pathogen('meta', 'first_seen'), 'w'):
                    pass
            for profile in config['profiles']:
                lg = f'{feed} {profile} {entry_info["id"]}'
                if profile in config['feeds'][feed]['profiles']:
                    live_status = entry_info.get('live_status')
                    if live_status == 'is_live':
                        if _live_enabled(lg, config, profile):
                            if config['profiles'][profile]['video']:
                                _start_process(live_video, config, feed,
                                               entry_pathogen, profile)
                            else:
                                _start_process(live_audio, config, feed,
                                               entry_pathogen, profile)
                    else:
                        if _download_enabled(lg, config, profile):
                            _start_process(download, config, feed,
                                           entry_pathogen, profile)

        time.sleep(feed_cfg['poll_seconds'] * (1 - random.random() / 100))

        c = cleanup(config, feed, feed_pathogen)
        if c:
            print(f'{feed}: cleaned up {len(c)} items.')


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


def _remove_dir(feed, entry_id, path):
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
        print(f'{feed} {entry_id}: removed', file=sys.stderr)


def cleanup(config, feed, feed_pathogen):
    now = time.time()
    to_remove = []
    keep_entries = config['feeds'][feed]['keep_entries']
    keep_entries_seconds = config['feeds'][feed]['keep_entries_seconds']
    id_ts = [(i, _entry_ts(feed_pathogen, feed, i))
             for i in os.listdir(feed_pathogen('meta'))
             if os.path.isdir(feed_pathogen('meta', i))]
    id_ts = sorted(id_ts, key=lambda p: p[1])[::-1]
    id_ts = id_ts[keep_entries:]
    id_ts = [(i, ts) for i, ts in id_ts if now - ts > keep_entries_seconds]
    for i, ts in id_ts:
        for path in [feed_pathogen(d, i) for d in ('meta', 'tmp', 'out')]:
            _remove_dir(feed, i, path)
        if config['paths']['live']:
            for p in glob.glob(os.path.join(config['paths']['live'], '*',
                                            feed, f'*.{i[:4]}.*')):
                os.unlink(p)
                print(f'{feed} {i}: removed live {p}', file=sys.stderr)
    return id_ts


def main(config):
    monitors = []
    for feed in config['feeds']:
        monitors.append(_start_process(monitor, config, feed))
        time.sleep(random.random() * 5)
    for p in monitors:
        p.join()
