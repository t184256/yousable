# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import hashlib
import json
import math
import os
import sys
import time

import cachetools.func
import requests
import yt_dlp.postprocessor.sponsorblock


API_URL = 'https://sponsor.ajay.app'


CATEGORIES = yt_dlp.postprocessor.sponsorblock.SponsorBlockPP.CATEGORIES.keys()
CATEGORIES = list(CATEGORIES)


def strtime(seconds):
    seconds = round(seconds)
    if seconds > 3600:
        h, r = seconds // 3600, seconds % 3600
        m, s = r // 60, r % 60
        return f'{h}:{m:02d}:{s:02d}'
    else:
        m, s = seconds // 60, seconds % 60
        return f'{m}:{s:02d}'


def _strip(r, categories=CATEGORIES):
    return {
        'videoID': r['videoID'],
        'segments': [
            {
                'actionType': s['actionType'],
                'category': s['category'],
                'segment': s['segment'],
                'videoDuration': s['videoDuration'],
            }
            for s in r['segments']
        ]
    } if r is not None else None


@cachetools.func.ttl_cache(maxsize=2048, ttl=5*60)
def query(video_id, strip=True, timeout=30, retry=5):
    h = hashlib.sha256(video_id.encode()).hexdigest()
    url = f'{API_URL}/api/skipSegments/{h[:4]}'

    r = None
    for i in range(retry):
        try:
            j = requests.get(url, timeout=timeout).json()
            for je in j:
                if je['videoID'] == video_id:
                    r = je
            break
        except Exception as e:
            print(f'sponsorblock error {i}/{retry}: {e}', file=sys.stderr)
            time.sleep(timeout/10)
    if r is not None:
        print(f'sponsorblock: {len(r["segments"])} segments for {video_id}',
              file=sys.stderr)
        assert 'segments' in r
        for s in r['segments']:
            assert 'actionType' in s
            assert 'category' in s
            assert 'segment' in s
            assert 'videoDuration' in s
            assert len(s['segment']) == 2
    else:
        print(f'sponsorblock: no segments for {video_id}', file=sys.stderr)
    return _strip(r) if strip else r


def pretty(r):
    t = 'Sponsorblock:\n'
    for s in r['segments']:
        t += f'* {s["actionType"]} {s["category"]}:'
        t += f' {strtime(s["segment"][0])} - {strtime(s["segment"][1])}\n'
    return t


def file_read(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as ex:
            print(ex, file=sys.stderr)


def file_write(sb, filepath):
    if sb is not None:  # TODO: this introduces a hysteresis
        with open(filepath + '.new', 'w') as f:
            json.dump(sb, f)
        os.rename(filepath + '.new', filepath)


def is_outdated(sb_prev, sb_new):
    # TODO: be smarter, consider categories? `all` could be a problem
    if not sb_prev and not sb_new:  # [] <-> None coercion
        return False
    return sb_prev != sb_new


class SponsorBlockPPCached(yt_dlp.postprocessor.sponsorblock.SponsorBlockPP):
    def _get_sponsor_segments(self, video_id, _unused_service):
        r = query(video_id, strip=True)
        return _strip(r, categories=self._categories)['segments']
