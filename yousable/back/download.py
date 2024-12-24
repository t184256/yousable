# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import os
import shutil
import sys
import time

import ffmpeg
import yt_dlp
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.ffmpeg import (
    FFmpegEmbedSubtitlePP,
    FFmpegExtractAudioPP,
    FFmpegVideoRemuxerPP,
)
from yt_dlp.postprocessor.modify_chapters import ModifyChaptersPP

import yousable.sponsorblock
from yousable.sponsorblock import SponsorBlockPPCached
from yousable.utils import proctitle, sleep


def shorten(s, to=30):
    return s[:to-1] + '…' if len(s) > 30 else s


def _add_postprocessor(ydl, pp, **kwargs):
    ydl.add_post_processor(pp(ydl, **kwargs), when='post_process')


def make_progress_hook(log_prefix, progressfile, target_interval=20):
    last_reported_time = 0
    progresses, last_reported_progresses = {}, {}
    def progress_hook(d):
        nonlocal progresses, last_reported_progresses, last_reported_time
        now = time.time()

        if (d.get('downloaded_bytes') is not None
                and d.get('total_bytes') is not None):
            i, l = d.get('downloaded_bytes'), d.get('total_bytes')
        elif (d.get('fragment_index') is not None
                and d.get('fragment_count') is not None):
            i, l = d.get('fragment_index'), d.get('fragment_count')
        else:
            return

        progresses[d['filename']] = i / l

        if (len(progresses) != len(last_reported_progresses) or
                (any(p1 > p2 + .1
                 for p1, p2 in zip(progresses.values(),
                                   last_reported_progresses.values()))) or
                now > last_reported_time + target_interval):
            pretty_progresses = ' '.join(f'{int(x * 100):3}%'
                                         for x in progresses.values())
            print(f'{log_prefix}: {pretty_progresses}', file=sys.stderr)
            with open(progressfile + '.tmp', 'w') as f:
                f.write(pretty_progresses)
            os.rename(progressfile + '.tmp', progressfile)
            print(f'{log_prefix}: {pretty_progresses}', file=sys.stderr)
            proctitle(pretty_progresses)
            last_reported_progresses = progresses.copy()
            last_reported_time = now

    return progress_hook


def download(config, feed, entry_pathogen, profile, retries=2):
    progressfile = entry_pathogen('tmp', profile, 'progress')
    start = time.time()

    entry_json = entry_pathogen('meta', 'entry.json')
    with open(entry_json) as f:
        entry_info = json.load(f)

    live_status = entry_info.get('live_status')
    if live_status in ('is_upcoming', 'is_live'):
        print(f'{feed} {entry_info["id"]}: {live_status=}', file=sys.stdout)
        return

    container = config['profiles'][profile]['container']
    audio_only = not config['profiles'][profile]['video']
    sb_cats = config['feeds'][feed]['sponsorblock_remove']

    pretty_log_name = f'{profile} {entry_info["id"]} {entry_info["title"]}'
    pretty_log_name = shorten(pretty_log_name)

    sb = None
    sb_global_path = entry_pathogen('meta', 'sponsorblock.json')
    sb_specific_path = entry_pathogen('out', f'.{profile}.sponsorblock.json')
    if sb_cats:
        proctitle('querying sponsorblock...')
        sb = yousable.sponsorblock.query_cached(entry_info["id"],
                                                sb_global_path)
        sb_prev = yousable.sponsorblock.file_read(sb_specific_path)
        if os.path.exists(entry_pathogen('out', profile + '.' + container)):
            if not yousable.sponsorblock.is_outdated(sb_prev, sb):
                print(f'{pretty_log_name} has already been downloaded',
                      file=sys.stderr)
                proctitle('done, already downloaded')
                return
            else:
                print(f'{pretty_log_name} SponsorBlock data out of date, '
                  're-downloading...', file=sys.stderr)
    else:
        if os.path.exists(entry_pathogen('out', profile + '.' + container)):
            print(f'{pretty_log_name} has already been downloaded',
                  file=sys.stderr)
            return

    retry = lambda n: min(64 * 2**n, 256)
    dl_opts = {
        'quiet': True,
        #'verbose': True,
        'keepvideo': True,
        'keepfragments': True,
        'skip_unavailable_fragments': False,
        'noprogress': True,
        'progress_hooks': [make_progress_hook(pretty_log_name, progressfile)],
        'outtmpl': 'media',
        'merge_output_format': container,
        'writethumbnail': True,
        'writesubtitles': True,
        'subtitleslangs': ['all', '-live_chat'],
        'paths': {
            'temp': entry_pathogen('tmp', profile),
            'home': entry_pathogen('tmp', profile),
        },
        'sleep_interval': config['limits']['throttle_extra_seconds'] / 2,
        'max_sleep_interval_requests':
            config['limits']['throttle_extra_seconds'],
        'sleep_interval_requests':
            config['limits']['throttle_extra_seconds'],
        'retry_sleep_functions': {
            'http': retry, 'extractor': retry, 'fragment': retry,
        },
        **config['yt_dlp_options']['all'],
        **config['profiles'][profile]['download'],
    }

    os.makedirs(entry_pathogen('out'), exist_ok=True)
    os.makedirs(entry_pathogen('tmp', profile), exist_ok=True)

    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            if sb and sb_cats:
                _add_postprocessor(ydl, FFmpegVideoRemuxerPP,
                                   preferedformat=container)
                _add_postprocessor(ydl, FFmpegEmbedSubtitlePP)
                _add_postprocessor(ydl, SponsorBlockPPCached,
                                   categories=sb_cats,
                                   cachefile=sb_global_path)
                _add_postprocessor(ydl, ModifyChaptersPP,
                                   remove_sponsor_segments=sb_cats,
                                   force_keyframes=False)  # so much faster
            if audio_only:
                _add_postprocessor(ydl, FFmpegExtractAudioPP,
                                   preferredcodec=container)
            if not audio_only:
                _add_postprocessor(ydl, EmbedThumbnailPP)

            sleep(f'pre-dl {pretty_log_name}', config=config)
            proctitle(f'dl {pretty_log_name}...')
            print(f'{pretty_log_name} begins downloading', file=sys.stderr)

            # doesn't re-sort formats
            #r = ydl.download_with_info_file(entry_pathogen('meta', 'entry.json'))
            url = (entry_info.get('original_url') or
                   entry_info.get('webpage_url') or
                   entry_info.get('url'))
            r = ydl.download(url)
            assert r == 0
    except yt_dlp.utils.UserNotLive as ex:
        print(f'{feed} {entry_info["id"]} ERROR: {ex}', file=sys.stdout)
        shutil.rmtree(entry_pathogen('tmp', profile))
        # suppress
    except yt_dlp.utils.DownloadError as ex:
        print(f'{feed} {entry_info["id"]} ERROR: {ex}', file=sys.stdout)
        shutil.rmtree(entry_pathogen('tmp', profile))
        raise

    proctitle('moving...')
    with open(progressfile + '.tmp', 'w') as f:
        f.write('moving...')
    os.rename(progressfile + '.tmp', progressfile)

    tmp_fname = entry_pathogen('tmp', profile, 'media.' + container)
    if not os.path.exists(tmp_fname):
        # some really weird bug where extension gets eaten?
        tmp_fname = entry_pathogen('tmp', profile, '.' + container)
        if not os.path.exists(tmp_fname):
            # some really weird bug where filename gets eaten?
            tmp_fname = entry_pathogen('tmp', profile, 'media')
    assert os.path.exists(tmp_fname)
    reported_duration = entry_info.get('duration')
    real_duration = float(ffmpeg.probe(tmp_fname)['format']['duration'])
    print(f'{pretty_log_name} {reported_duration=} {real_duration=}',
          file=sys.stderr)
    if reported_duration:
        if not real_duration or real_duration < reported_duration * 0.4:
            shutil.rmtree(entry_pathogen('tmp', profile))
            print(f'{pretty_log_name} too short, {retries=}', file=sys.stderr)
            sleep(f'{pretty_log_name} short-retry-{retries}', config=config)
            if retries > 1:
                print(f'{pretty_log_name} retrying retries={retries-1}')
                download(config, feed, entry_pathogen, profile,
                         retries=retries - 1)
    shutil.move(tmp_fname, entry_pathogen('out', profile + '.' + container))
    if sb_cats:
        yousable.sponsorblock.file_write(sb, sb_specific_path)
    proctitle('cleaning...')
    shutil.rmtree(entry_pathogen('tmp', profile))
    proctitle('finished')
    print(f'{pretty_log_name} has finished downloading '
          f'in {time.time() - start:.1f}s')
