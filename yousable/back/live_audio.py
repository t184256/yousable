# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import glob
import json
import multiprocessing
import os
import shutil
import sys
import threading
import time

import yt_dlp
import ffmpeg
import fasteners


def get_duration(infile):
    infile = infile + '.part' if os.path.exists(infile + '.part') else infile
    try:
        return int(float(ffmpeg.probe(infile)['format']['duration']))
    except KeyError:
        print(f'ERROR {infile}: {ex}', file=sys.stderr)
        durations.append(0)
    except ffmpeg._run.Error as ex:
        print(f'ERROR {infile}: {ex}', file=sys.stderr)


def slice(infile, outbasename, outext, i, start_time=None, duration=None):
    infile = infile + '.part' if os.path.exists(infile + '.part') else infile
    tmp = f'{outbasename}.{i:02d}.tmp.{outext}'
    out = f'{outbasename}.{i:02d}.{outext}'
    if os.path.exists(out):
        return
    print(f'{out} encoding...', file=sys.stderr)
    input_ = ffmpeg.input(infile, ss=start_time, t=duration)
    ffmpeg.output(input_, tmp, acodec=outext, strict=-2)\
          .run(overwrite_output=True, quiet=True)
    assert os.path.exists(tmp)
    os.rename(tmp, out)
    print(f'{out} written', file=sys.stderr)


def slice_intermediate(infile, outbasename, outext, duration, slice_duration):
    for i in range(duration // slice_duration):
        slice(infile, outbasename, outext, i, i * slice_duration,
              slice_duration)
    return duration // slice_duration * slice_duration


def slice_final(infile, outbasename, outext, slice_duration):
    total_duration = get_duration(infile)
    slice_intermediate(infile, outbasename, outext,
                       total_duration, slice_duration)
    i = duration // slice_duration + 1
    rest_duration = total_duration - i * slice_duration
    slice(infile, outbasename, outext, i, i * slice_duration, rest_duration)
    return total_duration


def make_progress_hook(log_prefix, tmp_path, out_path, container,
                       slice_duration, fname_collector, target_interval=20):
    lock = threading.Lock()
    progress, last_reported_seg, last_reported_time = {}, -1, 0
    observed_duration = written_duration = 0
    def progress_hook(d):
        nonlocal progress, last_reported_seg, last_reported_time
        nonlocal observed_duration, written_duration
        now = time.time()

        if 'fragment_index' not in d or 'fragment_count' not in d:
            return
        if d['fragment_index'] is None or d['fragment_count'] is None:
            return

        i, l = d['fragment_index'], d['fragment_count']
        progress = (i, l)
        fname_collector.add(d['filename'])
        segments_pretty_progress = f'{i}/{l}'

        if (i != last_reported_seg
                or now > last_reported_time + target_interval):
            print(f'{log_prefix}: {written_duration}/{observed_duration}s'
                  f' of {segments_pretty_progress} segments')
            last_reported_seg, last_reported_time = i, now

        if i < 2:
            return

        if not lock.acquire(blocking=False):
            return  # something else is merging anyway
        input_ = os.path.join(tmp_path, d['filename'])
        try:
            observed_duration = get_duration(input_)
            if observed_duration < written_duration + slice_duration:
                return
            written_duration = slice_intermediate(input_,
                                                  out_path, container,
                                                  observed_duration,
                                                  slice_duration)
        finally:
            lock.release()

        print(f'{log_prefix}: {written_duration}/{observed_duration}s'
              f' of {segments_pretty_progress} segments')
        last_reported_seg, last_reported_time = i, now

    return progress_hook


def live_audio(config, feed, entry_pathogen, profile):
    lockfile = entry_pathogen('tmp', profile, 'lock')
    l = fasteners.process_lock.InterProcessLock(lockfile)
    l.acquire()
    print(f'{feed}: {lockfile}', file=sys.stderr)
    start = time.time()
    with open(entry_pathogen('meta', 'entry.json')) as f:
        entry_info = json.load(f)

    container = config['profiles'][profile]['container']
    assert not config['profiles'][profile]['video']

    pretty_log_name = f'{profile} {entry_info["id"]} {entry_info["title"]}'
    if len(pretty_log_name) > 30:
        pretty_log_name = pretty_log_name[:27] + '...'

    fname = f'{entry_info["upload_date"][4:]}.{entry_info["id"][:4]}.{profile}'
    dir_ = os.path.join(config['paths']['live'], profile, feed)

    fnames = set()
    dl_opts = {
        'quiet': True,
        #'verbose': True,
        'keepvideo': True,
        'skip_unavailable_fragments': False,
        'noprogress': True,
        'progress_hooks': [make_progress_hook(
            pretty_log_name,
            entry_pathogen('tmp', profile),
            os.path.join(dir_, fname),
            container,
            config['feeds'][feed]['live_slice_seconds'],
            fnames
        )],
        'outtmpl': 'media',
        'paths': {
            'temp': entry_pathogen('tmp', profile),
            'home': entry_pathogen('tmp', profile),
        },
        'live_from_start': True,
        **config['profiles'][profile]['live'],
        'allow_unplayable_formats': True  # should prevent final yt-dlp merging
    }

    os.makedirs(dir_, exist_ok=True)
    os.makedirs(entry_pathogen('tmp', profile), exist_ok=True)

    while True:
        def subp():
            try:
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    # doesn't re-sort formats
                    #r = ydl.download_with_info_file(...)
                    r = ydl.download(entry_info['original_url'])
                    if r == 0:
                        os._exit(0)
            except Exception as ex:
                print('>>>', 'CAUGHT', type(ex), ex, file=sys.stderr)
                raise
            print('>>>', 'DEAD', file=sys.stderr)
            sys.stderr.flush()
            os._exit(1)
        for x in glob.glob(entry_pathogen('tmp', profile, '*-Frag*')):
            os.unlink(x)
        p = multiprocessing.Process(target=subp)
        print('>>>', 'started...', file=sys.stderr)
        p.start()
        print('>>>', 'joining...', file=sys.stderr)
        p.join()
        print('>>>', 'sleeping...', file=sys.stderr)
        time.sleep(10)
        print('>>>', 'restarting...', file=sys.stderr)
        if p.exitcode:
            continue

    input_ = [entry_pathogen('tmp', profile, x) for x in fnames][0]
    slice_final(input_, os.path.join(dir_, fname), container,
                config['feeds'][feed]['live_slice_seconds'])

    #shutil.rmtree(entry_pathogen('tmp', profile))

    l.release()
    print(f'{pretty_log_name} has finished downloading '
          f'in {time.time() - start:.1f}s')
