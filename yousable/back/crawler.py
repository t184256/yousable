# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import datetime
import json
import os
import pathlib
import pytz
import random
import sys
import time

import yt_dlp

from yousable.utils import sleep, proctitle, dl_options
from yousable.back.rss_timestamp import latest_timestamp_of_feeds


class MyStripPP(yt_dlp.postprocessor.PostProcessor):
    def run(self, info):
        """Strip heavy attributes that yousable-front just doesn't use."""
        if 'automatic_captions' in info:
            del info['automatic_captions']
        if 'requested_formats' in info:
            del info['requested_formats']
        if 'formats' in info:
            for fmt in info['formats']:
                if 'fragments' in fmt:
                    del fmt['fragments']
                if 'http_headers' in fmt:
                    del fmt['http_headers']
        if 'heatmap' in info:
            del info['heatmap']  # it's cool tho
        return [], info


def _write_json(path, data):
    with open(path + '.new', 'w') as f:
        json.dump(data, f)
    os.rename(path + '.new', path)


def feed_overduedness(config, feed, now):
    def feed_pathogen(d, *r):
        return os.path.join(config['paths'][d], feed, *r)

    feed_cfg = config['feeds'][feed]

    # Is it time to check it already?
    checked_marker_file = feed_pathogen('meta', 'checked')
    if os.path.exists(checked_marker_file):
        t = os.stat(checked_marker_file).st_mtime
        next_check = feed_cfg['poll_seconds'] + t
        return now - next_check
    return float('inf')


def most_overdue_feeds(config, top=2):
    t = time.time()
    d = {feed: feed_overduedness(config, feed, t) for feed in config['feeds']}
    d = {feed: overduedness for feed, overduedness in d.items()
         if overduedness > 0}
    if d:
        lo = len(d)
        d = dict(sorted(d.items(), key=lambda a: -a[1])[:top])
        print(f'{lo} feeds are overdue. Top {len(d)} overdue feeds:',
              file=sys.stderr)
        for feed, overduedness in d.items():
            print(f'{overduedness:7.1f}s {feed}', file=sys.stderr)
    else:
        print('all caught up', file=sys.stderr)
    return d


def crawl_feed(config, feed):
    def feed_pathogen(d, *r):
        return os.path.join(config['paths'][d], feed, *r)

    feed_cfg = config['feeds'][feed]
    #print(feed, feed_cfg)

    # Is it time to check it already?
    checked_marker_file = feed_pathogen('meta', 'checked')
    if os.path.exists(checked_marker_file):
        t = os.stat(checked_marker_file).st_mtime
        next_check = feed_cfg['poll_seconds'] + t
        if next_check > time.time():
            print(f'skipping {feed}: too early to check', file=sys.stderr)
            print('THIS SHOULD NEVER HAPPEN')
            raise RuntimeError('something is wrong with checked markers')

    ts_new = ts_prev = None
    if 'poll_rss_urls' in feed_cfg and feed_cfg['poll_rss_urls']:
        rss_timestamp_file = feed_pathogen('meta', 'rss_timestamp')
        if os.path.exists(rss_timestamp_file):
            with open(rss_timestamp_file) as f:
                ts_prev = f.read()
        sleep(f'{feed}: pre-RSS', variance_sec=0,
              base_sec=config['limits']['throttle_rss_seconds'])
        ts_new = str(latest_timestamp_of_feeds(feed_cfg['poll_rss_urls']))
        if ts_prev == ts_new:
            print(f'skipping {feed}: RSS timestamp is still {ts_new}',
                  file=sys.stderr)
            pathlib.Path(checked_marker_file).touch()
            return
        else:
            print(f'RSS timestamp: was {ts_prev}, is {ts_new}',
                  file=sys.stderr)
    else:
        print('no RSS urls configured, polling will be slow!', file=sys.stderr)

    extra_urls = feed_cfg.get('extra_urls') or []

    retry = lambda n: min(64 * 2**n, 256)
    yt_dl_options = {
        #'quiet': True,
        'ignoreerrors': True,  # do not crash on private videos
        'verbose': True,
        #'match_filter': yt_dlp.utils.match_filter_func(
        #    'live_status != is_upcoming'
        #),
        'extractor_retries': 3,
        'playlist_items': f'{feed_cfg["load_entries"]}::-1',
        'extractor_args': {'youtube': {'skip': ['translated_subs']}},
        'sleep_interval': config['limits']['throttle_extra_seconds'] / 2,
        'max_sleep_interval_requests':
            config['limits']['throttle_extra_seconds'],
        'sleep_interval_requests':
            config['limits']['throttle_extra_seconds'],
        'retry_sleep_functions': {'http': retry, 'extractor': retry},
        **dl_options(config, 'all'),
    }
    try:
        sleep(f'{feed}: pre-crawl 0/{len(extra_urls) + 1}', config=config)
        proctitle(f'{feed}: crawl...')
        print(f'{feed}: crawl...', file=sys.stderr)
        with yt_dlp.YoutubeDL(yt_dl_options) as ydl:
            ydl.add_post_processor(MyStripPP(), when='pre_process')
            info = ydl.extract_info(feed_cfg['url'], download=False)
        info = ydl.sanitize_info(info)
        assert info
    except Exception as ex:
        print(f'{feed}: ERROR {ex}', file=sys.stderr)
        sleep(f'{feed}: ERROR', config=config)

    if (
        info is None or
        not info['entries'] or
        all(e is None for e in info['entries'])
    ):
        print(f'{feed}: EMPTY entries={info["entries"]}', file=sys.stderr)
        return

    for extra_i, extra_url in enumerate(extra_urls):
        print(f'{feed} {len(info["entries"])}: '
              f'extra url check {extra_url}...', file=sys.stderr)
        try:
            sleep(f'{feed} pre-crawl {extra_i + 1}/{len(extra_urls) + 1}',
                  config=config)
            with yt_dlp.YoutubeDL(yt_dl_options) as ydl:
                ydl.add_post_processor(MyStripPP(), when='pre_process')
                ee = ydl.extract_info(extra_url, download=False)
            ee = ydl.sanitize_info(ee)

            if (
                ee is None or
                not ee['entries'] or
                all(e is None for e in ee['entries'])
            ):
                print(f'{feed}: EMPTY {extra_i} entries={ee["entries"]}',
                      file=sys.stderr)
                return
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

    now = datetime.datetime.now(datetime.timezone.utc)
    max_age = datetime.timedelta(seconds=feed_cfg['keep_entries_seconds'])
    max_age += datetime.timedelta(days=1)  # upload_date coarseness
    for entry_info in info['entries']:
        if entry_info is None:
            print('SKIPPING None', file=sys.stderr)
            continue
        if (entry_info.get('upload_date') and
                entry_info.get('live_status')
                not in ('is_live', 'is_upcoming')):
            udts = datetime.datetime.strptime(entry_info['upload_date'],
                                              '%Y%m%d')
            if now - pytz.utc.fromutc(udts) > max_age:
                print(f'skipping too old {entry_info["title"]}!',
                      file=sys.stderr)
                print(now - pytz.utc.fromutc(udts), max_age, file=sys.stderr)
                continue  # too old

        def entry_pathogen(d, *r):
            return feed_pathogen(d, entry_info['id'], *r)
        os.makedirs(entry_pathogen('meta'), exist_ok=True)
        _write_json(entry_pathogen('meta', 'entry.json'), entry_info)
        if not os.path.exists(entry_pathogen('meta', 'first_seen')):
            with open(entry_pathogen('meta', 'first_seen'), 'w'):
                pass

    os.makedirs(feed_pathogen('meta'), exist_ok=True)
    _write_json(feed_pathogen('meta', 'feed.json'), info)

    if ts_new is not None:
        with open(rss_timestamp_file, 'w') as f:
            f.write(ts_new)
    pathlib.Path(checked_marker_file).touch()
    refreshed_marker_file = feed_pathogen('meta', 'refreshed')
    pathlib.Path(refreshed_marker_file).touch()

    print(f'{feed} {len(info["entries"])}: refreshed.', file=sys.stderr)
    proctitle(f'{feed} refreshed')


def main(config):
    proctitle('spinning up...')
    while True:
        most_overdue = list(most_overdue_feeds(config, top=2).keys())
        if most_overdue:
            picked_feed = random.choice(most_overdue)
            crawl_feed(config, picked_feed)
        else:
            sleep('just chilling', config=config)
