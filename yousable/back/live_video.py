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
    print(f'slice: {outbasename} {start_time} {duration}', file=sys.stderr)
    if os.path.exists(out):
        return
    print(f'slicing...', file=sys.stderr)
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
    total_duration = min(get_durations(infiles))
    slice_and_merge_intermediate(infiles, outbasename, outext,
                                 total_duration, slice_duration)
    i = total_duration // slice_duration
    rest_duration = total_duration - i * slice_duration
    slice_and_merge(infiles, outbasename, outext, i, i * slice_duration,
                    rest_duration)
    return total_duration


class DownloadStuckError(RuntimeError):
    pass


def make_progress_hook(log_prefix, tmp_path, out_path, container,
                       slice_duration, fname_collector,
                       target_interval=20,
                       watchdog_stuck_max_desync=100,
                       watchdog_stuck_max_seconds=60):
    lock = threading.Lock()
    progresses, last_reported_segs, last_reported_time = {}, [], 0
    seg_log_desync, seg_log_timed = [], []
    observed_duration = written_duration = 0
    def progress_hook(d):
        nonlocal progresses, last_reported_segs, last_reported_time
        nonlocal seg_log_desync, seg_log_timed
        nonlocal observed_duration, written_duration
        now = time.time()

        if 'fragment_index' not in d or 'fragment_count' not in d:
            return
        if d['fragment_index'] is None or d['fragment_count'] is None:
            return

        i, l = d['fragment_index'], d['fragment_count']
        progresses[d['filename']] = (i, l)
        segments_pretty_progress = ' & '.join(f'{i}/{l}'
                                              for i, l in progresses.values())
        segs = tuple([i for i, _ in progresses.values()])
        if len(segs) < 2:
            return
        min_ = min(segs)
        max_ = max(l for _, l in progresses.values())

        seg_log_timed.append((now, segs))
        if not seg_log_desync or seg_log_desync[-1] != segs:
            seg_log_desync.append(segs)
        if len(seg_log_desync) > watchdog_stuck_max_desync:
            seg_log_desync = seg_log_desync[-watchdog_stuck_max_desync:]
        if seg_log_timed[0][0] < now - watchdog_stuck_max_seconds:
            # kill if no progress whatsoever for watchdog_stuck_max_seconds
            if len({s for _, s in seg_log_timed}) < 2:
                raise DownloadStuckError()
            # kill if progress is lopsided for watchdog_stuck_max_desync
            if len(seg_log_desync) >= watchdog_stuck_max_desync:
                if len({a for a, _ in seg_log_desync}) == 1:
                    raise DownloadStuckError()
                if len({b for _, b in seg_log_desync}) == 1:
                    raise DownloadStuckError()
            # trim timed list
            while (seg_log_timed
                   and seg_log_timed[0][0] < now - watchdog_stuck_max_seconds):
                seg_log_timed.pop(0)


        if (segs != last_reported_segs
                or now > last_reported_time + target_interval):
            print(f'{log_prefix}: {written_duration}/{observed_duration}s'
                  f' of {segments_pretty_progress} segments', file=sys.stderr)
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
              f' of {segments_pretty_progress} segments', file=sys.stderr)
        last_reported_segs, last_reported_time = segs, now

        if fname_collector.empty():
            fname_collector.put(set(progresses.keys()))

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

    fname_collector = multiprocessing.Queue()
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
            fname_collector
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
        fnames = set()
        def subp():
            try:
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    # doesn't re-sort formats
                    #r = ydl.download_with_info_file(...)
                    r = ydl.download(entry_info['webpage_url'])
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
        finmedia = entry_pathogen('tmp', profile, 'media')
        if not fname_collector.empty():
            fnames.update(fname_collector.get())
        print('>>>', f'{p.exitcode} {os.path.exists(finmedia)}',
              file=sys.stderr)
        if p.exitcode == 0 or os.path.exists(finmedia):
            print('>>>', 'done! proceeding to final slicing', file=sys.stderr)
            break
        else:
            print('>>>', 'sleeping...', file=sys.stderr)
            time.sleep(10)
            print('>>>', 'restarting...', file=sys.stderr)

    if os.path.exists(finmedia):
        inputs = [finmedia]
    else:
        inputs = [entry_pathogen('tmp', profile, x) for x in fnames]
    print('>>>', f'merging ({inputs})...', file=sys.stderr)
    slice_and_merge_final(inputs, os.path.join(dir_, fname), container,
                          config['feeds'][feed]['live_slice_seconds'])

    #shutil.rmtree(entry_pathogen('tmp', profile))

    l.release()
    print(f'{pretty_log_name} has finished downloading '
          f'in {time.time() - start:.1f}s')
