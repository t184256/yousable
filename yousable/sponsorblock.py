# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import hashlib
import json
import math
import os
import sys
import time

import requests
import yt_dlp.postprocessor.sponsorblock


API_URL = 'https://sponsor.ajay.app'


CATEGORIES = yt_dlp.postprocessor.sponsorblock.SponsorBlockPP.CATEGORIES.keys()
CATEGORIES = list(CATEGORIES)


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


def query(video_id, strip=True, timeout=30, retry=5):
    h = hashlib.sha256(video_id.encode()).hexdigest()
    url = f'{API_URL}/api/skipSegments/{h[:4]}'

    r = None
    for i in range(retry):
        try:
            resp = requests.get(url, timeout=timeout)
            print(resp, url, file=sys.stderr)
            if resp.status_code in (502, 503):
                break
            j = resp.json()
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


def file_read(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as ex:
            print(ex, file=sys.stderr)


def file_write(sb, filepath):
    with open(filepath + '.new', 'w') as f:
        json.dump(sb, f)
    os.rename(filepath + '.new', filepath)


def is_outdated(sb_prev, sb_new):
    # TODO: be smarter, consider categories? `all` could be a problem
    if not sb_prev and not sb_new:  # [] <-> None coercion
        return False
    return sb_prev != sb_new


def query_cached(video_id, cachepath, max_age=900):
    # one megaoperation. query or use stale if unreacheable + caching in file
    if os.path.exists(cachepath):
        if os.stat(cachepath).st_mtime > time.time() - max_age:
            print(f'{video_id} reusing fresh enough SponsorBlock data',
                  file=sys.stderr)
            sb = file_read(cachepath)
            return sb
    sb_new = query(video_id, strip=True)
    sb_prev = file_read(cachepath)
    if sb_new is None and sb_prev is not None:
        # weird case: unreacheable SponsorBlock server
        # but we have a previous result and we don't want to reencode
        # comes at the cost of not restoring a segment
        # if it was the only one flagged and was consequently unflagged
        print(f'{video_id} reusing stale SponsorBlock data',
              file=sys.stderr)
        return sb_prev  # do not overwrite old result
    print(f'{video_id} writing new SponsorBlock data', file=sys.stderr)
    file_write(sb_new, cachepath)
    return sb_new


class SponsorBlockPPCached(yt_dlp.postprocessor.sponsorblock.SponsorBlockPP):
    def __init__(self, *args, cachefile=None, **kwargs):
        super(SponsorBlockPPCached, self).__init__(*args, **kwargs)
        self.cachefile = cachefile

    def _get_sponsor_segments(self, video_id, _unused_service):
        r = query_cached(video_id, self.cachefile)
        print(r)
        return _strip(r, categories=self._categories)['segments'] if r else []
