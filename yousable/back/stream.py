# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import glob
import multiprocessing
import os
import shutil
import sys
import time

import yt_dlp

import ffmpeg
import fasteners


def shorten(s, to=30):
    return s[:to-1] + '…' if len(s) > 30 else s


def guess_file(dir_):
    def maybe(g):
        if r := glob.glob(os.path.join(dir_, g)):
            return r[0]
    return maybe('media') or maybe('media.part') or maybe('media.f*.part')


def get_duration(infile):
    try:
        return int(float(ffmpeg.probe(infile)['format']['duration']))
    except KeyError as ex:
        print(f'ERROR {infile}: {type(ex)} {ex}', file=sys.stderr)
    except ffmpeg._run.Error as ex:
        print(f'ERROR {infile}: {type(ex)} {ex}', file=sys.stderr)


def slice_and_merge(infiles, outbasename, outext, i,
                    start_time=None, duration=None, audio_only=False):
    infiles = [f + '.part' if os.path.exists(f + '.part') else f
               for f in infiles]
    tmp = f'{outbasename}.{i:02d}.tmp.{outext}'
    out = f'{outbasename}.{i:02d}.{outext}'
    print(f'slice: {outbasename} {i} {start_time} {duration}',
          file=sys.stderr)
    if os.path.exists(out):
        return
    print(f'slicing...', file=sys.stderr)
    extra_kwargs = {}
    if start_time is not None:
        extra_kwargs['ss'] = start_time
    if duration is not None:
        extra_kwargs['t'] = duration
    inputs = [ffmpeg.input(f, **extra_kwargs) for f in infiles]
    if not audio_only:
        ffmpeg.output(*inputs, tmp, vcodec='copy', acodec='copy')\
              .run(overwrite_output=True, quiet=True)
    else:
        ffmpeg.output(*inputs, tmp, acodec=outext, strict=-2)\
              .run(overwrite_output=True, quiet=True)
    assert os.path.exists(tmp)
    os.rename(tmp, out)
    print(f'{out} written', file=sys.stderr)


def slice_and_merge_intermediate(infiles, outbasename, outext,
                                 duration, slice_duration, audio_only=False):
    for i in range(duration // slice_duration):
        slice_and_merge(infiles, outbasename, outext, i, i * slice_duration,
                        slice_duration, audio_only=audio_only)
    return duration // slice_duration * slice_duration


def slice_and_merge_final(infiles, outbasename, outext, slice_duration,
                          audio_only=False):
    total_duration = min([get_duration(f) for f in infiles])
    slice_and_merge_intermediate(infiles, outbasename, outext,
                                 total_duration, slice_duration,
                                 audio_only=audio_only)
    i = total_duration // slice_duration
    slice_and_merge(infiles, outbasename, outext, i, i * slice_duration,
                    audio_only=audio_only)
    return total_duration


def make_progress_hook(log_prefix, target_interval=20):
    last_reported_seg, last_reported_time = -1, 0
    def progress_hook(d):
        nonlocal last_reported_seg, last_reported_time
        now = time.time()

        if 'fragment_index' not in d or 'fragment_count' not in d:
            return
        if d['fragment_index'] is None or d['fragment_count'] is None:
            return

        i, l = d['fragment_index'], d['fragment_count']
        segments_pretty_progress = f'{i}/{l}'

        if (i - last_reported_seg >= 10 and i % 10 == 0
                or now > last_reported_time + target_interval):
            print(f'{log_prefix}: {segments_pretty_progress} segments',
                  file=sys.stderr)
            last_reported_seg, last_reported_time = i, now

    return progress_hook


def intermerger(log_prefix, dirs, outbasename, outext, slice_duration,
                its_over_event, audio_only=False):
    observed_duration = written_duration = 0

    while not its_over_event.wait(timeout=min(10, slice_duration//32+1)):
        infiles = [guess_file(d) for d in dirs]
        durations = [get_duration(f) for f in infiles if f is not None]
        durations = [d for d in durations if d is not None]
        if len(durations) < len(dirs):
            print(f'{log_prefix}: {written_duration}/{observed_duration}s'
                  f' of {"+".join(str(d) for d in durations)}+???s',
                  file=sys.stderr)
            return
        observed_duration = min(durations)

        print(f'{log_prefix}: {written_duration}/{observed_duration}s'
              f' of {"+".join(str(d) for d in durations)}s',
              file=sys.stderr)

        if observed_duration > written_duration + slice_duration:
            written_duration = \
                slice_and_merge_intermediate(infiles, outbasename, outext,
                                             observed_duration, slice_duration,
                                             audio_only=audio_only)
            print(f'{log_prefix}: {written_duration}/{observed_duration}s'
                  f' of {"+".join(str(d) for d in durations)}s',
                  file=sys.stderr)
    print('intermerger done', file=sys.stderr)


def _stream(config, entry_info, feed, workdir, profile, video=False):
    video_or_audio = 'video' if video else 'audio'
    live_profile_cfg = config['profiles'][profile]['live']
    live_opts = live_profile_cfg.get('video' if video else 'audio', {})
    if live_opts.get('format', None) is None:
        live_opts['format'] = 'bv[acodec=none]' if video else 'ba[vcodec=none]'

    pretty_log_name = (f'{profile}/{"v" if video else "a"}'
                       f' {entry_info["id"]} {entry_info["title"]}')
    pretty_log_name = shorten(pretty_log_name)
    dl_opts = {
        'quiet': True,
        #'verbose': True,
        'keepvideo': True,
        'skip_unavailable_fragments': False,
        'noprogress': True,
        'progress_hooks': [make_progress_hook(pretty_log_name)],
        'outtmpl': 'media',
        'paths': {
            'temp': workdir,
            'home': workdir,
        },
        'live_from_start': True,
        **live_opts,
    }

    os.makedirs(workdir, exist_ok=True)

    url = entry_info['webpage_url']
    while True:
        for x in glob.glob(os.path.join(workdir, '*-Frag*')):
            os.unlink(x)
        try:
            # we need fresh data
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get('live_status') != 'is_live':
                    print(pretty_log_name,
                          f'NOT LIVE ANYMORE, {info.get("live_status")}',
                          file=sys.stderr)
                    continue

            pretty_log_name = (f'{profile}/{"v" if video else "a"}'
                               f'{entry_info["id"]} {entry_info["title"]}')
            pretty_log_name = shorten(pretty_log_name)
            container = config['profiles'][profile]['container']

            # we need data with formats resorted according to profile
            # and writing an info_file is too much hassle, FIXME
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                r = ydl.download(url)
                if r == 0:
                    os._exit(0)
        except Exception as ex:
            print(pretty_log_name, 'ERROR', type(ex), ex, file=sys.stderr)
            print(pretty_log_name, 'sleeping...', file=sys.stderr)
            time.sleep(5)
            print(pretty_log_name, 'restarting...', file=sys.stderr)
    print(pretty_log_name, 'done', file=sys.stderr)


def stream(config, feed, entry_info, entry_pathogen, profile, video=True):
    pretty_log_name = f'{profile}/s {entry_info["id"]} {entry_info["title"]}'
    pretty_log_name = shorten(pretty_log_name)

    lockfile = entry_pathogen('tmp', profile, 'lock')
    print(f'{pretty_log_name}: {lockfile}...', file=sys.stderr)
    l = fasteners.process_lock.InterProcessLock(lockfile)
    l.acquire()
    print(f'{pretty_log_name}: {lockfile} acquired.', file=sys.stderr)

    fname = f'{entry_info["upload_date"][4:]}.{entry_info["id"][:4]}.{profile}'
    dir_ = os.path.join(config['paths']['live'], profile, feed)
    outbasename = os.path.join(dir_, fname)
    outext = config['profiles'][profile]['container']
    dir_audio = entry_pathogen('tmp', profile, 'audio')
    dir_video = entry_pathogen('tmp', profile, 'video')
    merge_dirs = [dir_video, dir_audio] if video else [dir_audio]
    slice_seconds = config['feeds'][feed]['live_slice_seconds']

    os.makedirs(dir_, exist_ok=True)
    if video:
        stream_video_p = multiprocessing.Process(
                target=_stream,
                args=(config, entry_info, feed, dir_video, profile, True)
        )
        stream_video_p.start()
    stream_audio_p = multiprocessing.Process(
            target=_stream,
            args=(config, entry_info, feed, dir_audio, profile, False)
    )
    stream_audio_p.start()
    its_over_event = multiprocessing.Event()
    intermerger_p = multiprocessing.Process(
            target=intermerger,
            args=(pretty_log_name, merge_dirs, outbasename, outext,
                  slice_seconds, its_over_event, not video)
    )
    intermerger_p.start()

    if video:
        stream_video_p.join()
    stream_audio_p.join()
    print('>>>', 'it\'s over...', file=sys.stderr)
    its_over_event.set()
    intermerger_p.join()
    print('>>>', 'intermerger has finished...', file=sys.stderr)

    slice_and_merge_final(merge_dirs, outbasename, outext, slice_seconds,
                          audio_only=audio_only)

    l.release()
    print(f'{pretty_log_name} has finished livestreaming '
          f'in {time.time() - start:.1f}s')

    if video:
        shutil.rmtree(dir_video)
    shutil.rmtree(dir_audio)
