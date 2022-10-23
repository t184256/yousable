# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import multiprocessing
import os
import shutil
import time

import fasteners
import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegEmbedSubtitlePP
from yt_dlp.postprocessor.ffmpeg import FFmpegVideoRemuxerPP
from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.postprocessor.modify_chapters import ModifyChaptersPP

import yousable.sponsorblock
from yousable.sponsorblock import SponsorBlockPPCached


def _add_postprocessor(ydl, pp, **kwargs):
    ydl.add_post_processor(pp(ydl, **kwargs), when='post_process')


def make_progress_hook(prefix, max_silence=20):
    reported_progresses, progresses, last_report_time = {}, {}, 0
    def progress_hook(d):
        nonlocal reported_progresses, progresses, last_report_time

        if ('downloaded_bytes' in d and 'total_bytes' in d
                and d['downloaded_bytes'] and d['total_bytes']):
            i, l = d['downloaded_bytes'], d['total_bytes']
            if l < 2**20:
                return
        elif ('fragment_index' in d and 'fragment_count' in d
                and d['fragment_index'] and d['fragment_count']):
            i, l = d['fragment_index'], d['fragment_count']
        else:
            return
        progresses[d['filename']] = i / l

        now = time.time()
        if (now - last_report_time > max_silence or
                [int(p * 10) for p in progresses.values()] !=
                [int(p * 10) for p in reported_progresses.values()]):
            log_msg = f'{prefix}:'
            for p in progresses.values():
                log_msg += f' {int(100 * p):3d}%'
            print(log_msg)
            reported_progresses, last_report_time = progresses.copy(), now
    return progress_hook


def download(config, feed, entry_pathogen, profile):
    lockfile = entry_pathogen('tmp', profile, 'lock')
    l = fasteners.process_lock.InterProcessLock(lockfile)
    l.acquire()
    with open(entry_pathogen('meta', 'entry.json')) as f:
        entry_info = json.load(f)

    sb_path = entry_pathogen('meta', 'sponsorblock.json')
    sb_cats = categories=config['feeds'][feed]['sponsorblock_remove']
    sb = None
    if sb_cats:
        if not sb:
            sb = yousable.sponsorblock.query(entry_info["id"], strip=True)
        if sb is None:
            # weird case: unreacheable SponsorBlock server
            # but we have a previous result and we don't want to reencode
            # comes at the cost of not restoring a segment
            # if it was the only one and was consequently removed
            if sb:
                print(f'{pretty_log_name} reusing old SponsorBlock data',
                      file=sys.stderr)
            sb_prev = yousable.sponsorblock.file_read(sb_path)

    pretty_log_name = f'{profile} {entry_info["id"]} {entry_info["title"]}'
    if len(pretty_log_name) > 40:
        pretty_log_name = pretty_log_name[:37] + '...'

    start = time.time()

    if os.path.exists(entry_pathogen('out', profile + '.mkv')):
        sb_prev = yousable.sponsorblock.file_read(sb_path)
        if sb_cats and yousable.sponsorblock.is_outdated(sb, sb_prev):
            print(f'{pretty_log_name} sponsorblock has updated, redownloading')
        else:
            print(f'{pretty_log_name} has already been downloaded')
            return

    dl_opts = {
        'quiet': True,
        #'verbose': True,
        'keepvideo': True,
        'keepfragments': True,
        'noprogress': True,
        'progress_hooks': [make_progress_hook(pretty_log_name)],
        'merge_output_format': 'mkv',
        'writethumbnail': True,
        'writesubtitles': True,
        'outtmpl': 'media',
        'subtitleslangs': ['all', '-live_chat'],
        'paths': {
            'temp': entry_pathogen('tmp', profile),
            'home': entry_pathogen('tmp', profile),
        },
        **config['profiles'][profile]['download'],
    }

    os.makedirs(entry_pathogen('out'), exist_ok=True)
    os.makedirs(entry_pathogen('tmp', profile), exist_ok=True)
    with yt_dlp.YoutubeDL(dl_opts) as ydl:
        if sb and sb_cats:
            _add_postprocessor(ydl, FFmpegVideoRemuxerPP, preferedformat='mkv')
            _add_postprocessor(ydl, FFmpegEmbedSubtitlePP)
            _add_postprocessor(ydl, SponsorBlockPPCached, categories=sb_cats)
            _add_postprocessor(ydl, ModifyChaptersPP,
                               remove_sponsor_segments=sb_cats,
                               force_keyframes=True)
            _add_postprocessor(ydl, EmbedThumbnailPP)
        # doesn't re-sort formats
        #r = ydl.download_with_info_file(entry_pathogen('meta', 'entry.json'))
        r = ydl.download(entry_info['original_url'])
        assert r == 0

    shutil.move(entry_pathogen('tmp', profile, 'media.mkv'),
                entry_pathogen('out', profile + '.mkv'))
    yousable.sponsorblock.file_write(sb, sb_path)
    #shutil.rmtree(entry_pathogen('tmp', profile))
    l.release()
    print(f'{pretty_log_name} has finished downloading '
          f'in {time.time() - start:.1f}s')
