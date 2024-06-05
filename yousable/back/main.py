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
from yousable.back.stream import stream
from yousable.utils import start_process, proctitle, reap


def stream_then_download(config, feed, entry_info, entry_pathogen,
                         profile, video):
    stream(config, feed, entry_info, entry_pathogen, profile, video)
    if _download_enabled(config, profile):
        time.sleep(900)
        download(config, feed, entry_pathogen, profile)


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


def _download_enabled(config, profile):
    if config['profiles'][profile]['download'] is None:
        return False
    return True


def monitor(config, feed):
    children = []
    while True:
        def feed_pathogen(d, *r):
            return os.path.join(config['paths'][d], feed, *r)

        feed_cfg = config['feeds'][feed]
        #print(feed, feed_cfg)

        retry = lambda n: min(2 * 2**n, 128)
        yt_dl_options = {
            'quiet': True,
            'ignoreerrors': True,  # do not crash on private videos
            #'verbose': True,
            'match_filter': yt_dlp.utils.match_filter_func(
                'live_status != is_upcoming'
            ),
            'playlist_items': f'{feed_cfg["load_entries"]}::-1'
            'retry_sleep_functions': {'http': retry, 'extractor': retry},
        }
        print(f'{feed}: refreshing...')
        proctitle('refreshing...')
        try:
            with yt_dlp.YoutubeDL(yt_dl_options) as ydl:
                info = ydl.extract_info(feed_cfg['url'], download=False)
            info = ydl.sanitize_info(info)
            assert info
        except Exception as ex:
            print(f'{feed}: ERROR {ex}', file=sys.stderr)
            time.sleep(feed_cfg['poll_seconds'] / 4)
            continue
        if feed_cfg['extra_urls']:
            for extra_url in feed_cfg['extra_urls']:
                print(f'{feed} {len(info["entries"])}: extra url check {extra_url}...')
                try:
                    with yt_dlp.YoutubeDL(yt_dl_options) as ydl:
                        ee = ydl.extract_info(extra_url, download=False)
                    ee = ydl.sanitize_info(ee)
                    ids = [x['id'] for x in info['entries']]
                    if ee and 'entries' in ee:
                        for eee in ee['entries']:
                            if eee is None:
                                print(f'{feed}: skipping a None entry',
                                      file=sys.stderr)
                                continue
                            if 'id' in eee and eee['id']:
                                if eee['id'] not in ids:
                                    print(f'{feed}: extra n {eee["id"]}',
                                          file=sys.stderr)
                                    info['entries'].append(eee)
                            else:
                                print(f'{feed}: what is {eee}', file=sys.stderr)
                    elif ee and 'id' in ee and ee['id'] not in ids:
                        print(f'{feed}: extra 1 {ee["id"]}', file=sys.stderr)
                        info['entries'].append(ee)
                    else:
                        print(f'{feed}: WHAT IS {ee}', file=sys.stderr)
                except Exception as ex:
                    print(f'{feed}: ERROR {ex} {extra_url}', file=sys.stderr)
        print(f'{feed} {len(info["entries"])}: refreshed.')
        proctitle('refreshed')

        os.makedirs(feed_pathogen('meta'), exist_ok=True)
        _write_json(feed_pathogen('meta', 'feed.json'), info)

        now = datetime.datetime.now(datetime.timezone.utc)
        max_age = datetime.timedelta(seconds=feed_cfg['keep_entries_seconds'])
        max_age += datetime.timedelta(days=1)  # upload_date coarseness
        for entry_info in info['entries']:
            if ('upload_date' in entry_info and entry_info['upload_date']
                    and entry_info.get('live_status') != 'is_live'):
                udts = datetime.datetime.strptime(entry_info['upload_date'],
                                                  '%Y%m%d')
                if now - pytz.utc.fromutc(udts) > max_age:
                    print(f'skipping too old {entry_info["title"]}!', file=sys.stderr)
                    print(now - pytz.utc.fromutc(udts), max_age, file=sys.stderr)
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
                            video = config['profiles'][profile]['video']
                            start_process(('stream_then_dl '
                                           f'{entry_info["id"]} {profile}'),
                                          stream_then_download,
                                          config, feed,
                                          entry_info, entry_pathogen,
                                          profile, video)
                    else:
                        if _download_enabled(config, profile):
                            start_process(('download '
                                           f'{entry_info["id"]} {profile}'),
                                          download,
                                          config, feed,
                                          entry_pathogen, profile)

        slp = max(15, feed_cfg['poll_seconds'] * (1 - random.random() / 100))
        proctitle('reaping...')
        time.sleep(15)
        reap()

        proctitle()
        time.sleep(slp - 15)

        proctitle('cleaning...')
        c = cleanup(config, feed, feed_pathogen)
        if c:
            print(f'{feed}: cleaned up {len(c)} items.')

        proctitle('reaping...')
        reap()


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
    proctitle('spinning up...')
    for feed in config['feeds']:
        monitors.append(start_process(f'monitor {feed}', monitor,
                                      config, feed))
        extra_count = len(feed['extra_urls']) if 'extra_urls' in feed else 0
        time.sleep(random.random() * 30 * (1 + extra_count))
    proctitle('up and running')
    for p in monitors:
        p.join()
