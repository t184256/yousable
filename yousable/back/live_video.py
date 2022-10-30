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


def get_durations(infiles):
    durations = []
    infiles = [f + '.part' if os.path.exists(f + '.part') else f
               for f in infiles]
    for f in infiles:
        try:
            durations.append(int(float(ffmpeg.probe(f)['format']['duration'])))
        except KeyError:
            print(f'ERROR {f}: {ex}', file=sys.stderr)
            durations.append(0)
        except ffmpeg._run.Error as ex:
            print(f'ERROR {f}: {ex}', file=sys.stderr)
    return durations


def slice_and_merge(infiles, outbasename, outext, i,
                    start_time=None, duration=None):
    infiles = [f + '.part' if os.path.exists(f + '.part') else f
               for f in infiles]
    tmp = f'{outbasename}.{i:02d}.tmp.{outext}'
    out = f'{outbasename}.{i:02d}.{outext}'
    if os.path.exists(out):
        return
    inputs = [ffmpeg.input(f, ss=start_time, t=duration) for f in infiles]
    ffmpeg.output(*inputs, tmp, vcodec='copy', acodec='copy')\
          .run(overwrite_output=True)#, quiet=True)
    assert os.path.exists(tmp)
    os.rename(tmp, out)
    print(f'{out} written', file=sys.stderr)


def slice_and_merge_intermediate(infiles, outbasename, outext,
                                 duration, slice_duration):
    for i in range(duration // slice_duration):
        slice_and_merge(infiles, outbasename, outext, i, i * slice_duration,
                        slice_duration)
    return duration // slice_duration * slice_duration


def slice_and_merge_final(infiles, outbasename, outext, slice_duration):
    total_duration = min(get_durations(inputs))
    slice_and_merge_intermediate(infiles, outbasename, outext,
                                 total_duration, slice_duration)
    i = duration // slice_duration + 1
    rest_duration = total_duration - i * slice_duration
    slice_and_merge(infiles, outbasename, outext, i, i * slice_duration,
                    rest_duration)
    return total_duration


class DownloadStuckError(RuntimeError):
    pass


def make_progress_hook(log_prefix, tmp_path, out_path, container,
                       slice_duration, fname_collector,
                       target_interval=20, watchdog_stuck_max=50):
    lock = threading.Lock()
    seg_log, progresses, last_reported_segs, last_reported_time = [], {}, [], 0
    observed_duration = written_duration = 0
    def progress_hook(d):
        nonlocal seg_log, progresses, last_reported_segs, last_reported_time
        nonlocal observed_duration, written_duration
        now = time.time()

        if 'fragment_index' not in d or 'fragment_count' not in d:
            return
        if d['fragment_index'] is None or d['fragment_count'] is None:
            return

        i, l = d['fragment_index'], d['fragment_count']
        progresses[d['filename']] = (i, l)
        fname_collector.add(d['filename'])
        segments_pretty_progress = ' & '.join(f'{i}/{l}'
                                              for i, l in progresses.values())
        segs = [(i) for i, _ in progresses.values()]
        if len(segs) < 2:
            return
        min_ = min(segs)
        max_ = max(l for _, l in progresses.values())

        seg_log_new = [i for i, _ in progresses.values()]
        if not seg_log or seg_log[-1] != seg_log_new:
            seg_log.append(seg_log_new)
        if len(seg_log) >= watchdog_stuck_max:
            seg_log = seg_log[-watchdog_stuck_max:]
            if len({a for a, _ in seg_log}) == 1:
                raise DownloadStuckError()
            if len({b for _, b in seg_log}) == 1:
                raise DownloadStuckError()

        if (segs != last_reported_segs
                or now > last_reported_time + target_interval):
            print(f'{log_prefix}: {written_duration}/{observed_duration}s'
                  f' of {segments_pretty_progress} segments')
            last_reported_segs, last_reported_time = segs, now

        if min_ < 2:
            return

        if not lock.acquire(blocking=False):
            return  # something else is merging anyway
        inputs = [os.path.join(tmp_path, x) for x in progresses.keys()]
        try:
            durations = get_durations(inputs)
            if len(durations) < 2:
                return
            observed_duration = min(durations)
            if observed_duration < written_duration + slice_duration:
                return
            written_duration = \
                    slice_and_merge_intermediate(inputs,
                                                 out_path, container,
                                                 observed_duration,
                                                 slice_duration)
        finally:
            lock.release()

        print(f'{log_prefix}: {written_duration}/{observed_duration}s'
              f' of {segments_pretty_progress} segments')
        last_reported_segs, last_reported_time = segs, now

    return progress_hook


def live_video(config, feed, entry_pathogen, profile):
    lockfile = entry_pathogen('tmp', profile, 'lock')
    l = fasteners.process_lock.InterProcessLock(lockfile)
    l.acquire()
    print(f'{feed}: {lockfile}', file=sys.stderr)
    start = time.time()
    with open(entry_pathogen('meta', 'entry.json')) as f:
        entry_info = json.load(f)

    container = config['profiles'][profile]['container']
    assert config['profiles'][profile]['video']

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
            except DownloadStuckError as ex:
                print('>>>', 'STUCK', file=sys.stderr)
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

    inputs = [entry_pathogen('tmp', profile, x) for x in fnames]
    slice_and_merge_final(inputs, os.path.join(dir_, fname), container,
                          config['feeds'][feed]['live_slice_seconds'])

    #shutil.rmtree(entry_pathogen('tmp', profile))

    l.release()
    print(f'{pretty_log_name} has finished downloading '
          f'in {time.time() - start:.1f}s')
