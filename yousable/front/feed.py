# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

#import concurrent.futures
#import itertools
#import types
import datetime
import json
import os
import pytz
import sys

import yt_dlp
import feedgen.feed

import yousable.front.best_thumbnail
import yousable.front.chapters_extensions


def generate_entry(config, profile, feed_name, url_maker, fg, entry_id,
                   entry_pathogen):
    meta_fname = entry_pathogen('meta', 'entry.json')
    if not os.path.exists(meta_fname):
        print(f"SKIPPING {feed_name} {entry_id}: no metadata", file=sys.stderr)
        return

    with open(meta_fname) as f:
        e = json.load(f)
    audio_video = 'video' if config['profiles'][profile]['video'] else 'audio'
    container = config['profiles'][profile]['container']
    mime = f'{audio_video}/{container}'

    fe = fg.add_entry()
    fe.id(e['id'])
    fe.link({'href': e['original_url']})

    title = e['fulltitle']
    live_status = e.get('live_status')
    if live_status and live_status != 'was_live':
        live_status = str(live_status).removeprefix('is_')
        title = f'[{live_status} {e["id"][:4]}] {title}'
    fe.title(title)

    description = e['description'] or e['fulltitle']
    alts = {}
    for _p in config['profiles']:
        _c = config['profiles'][_p]['container']
        _vp = os.path.join(entry_pathogen('out', f'{_p}.{_c}'))
        if os.path.exists(_vp):
            alts[_p] = url_maker(f'download/{feed_name}/{entry_id}.{_p}.{_c}')
    if alts:
        description = ('Stream using VLC: ' +
                       ', '.join(f'<a href="vlc://{_u}">{_p}</a>'
                                 for _p, _u in alts.items()) +
                       '\n\n' + description)
    fe.description(description)

    if 'duration' in e:
        fe.podcast.itunes_duration(e['duration'])
    if 'chapters' in e and e['chapters']:  # TODO: account for Sponsorblock
        for chapter in e['chapters']:
            fe.chapters.add(float(chapter['start_time']), chapter['title'])

    t = yousable.front.best_thumbnail.determine(e)
    if t:
        # HACK: bypass overzealous validation
        fe.podcast._PodcastEntryExtension__itunes_image = t

    if 'release_timestamp' in e and e['release_timestamp']:
        ts = datetime.datetime.utcfromtimestamp(e['release_timestamp'])
        ts = pytz.utc.fromutc(ts)
    else:
        fsts = os.stat(entry_pathogen('meta', 'first_seen')).st_mtime
        fsts = pytz.utc.localize(datetime.datetime.utcfromtimestamp(fsts))
        if 'upload_date' in e and e['upload_date']:
            udts = datetime.datetime.strptime(e['upload_date'], '%Y%m%d')
            udts = pytz.utc.fromutc(udts)
            if udts <= fsts <= udts + datetime.timedelta(days=1):
                ts = fsts  # first_seen is near upload_date and more precise
            else:
                ts = udts  # first_seen is wildly off and not helping
        else:
            ts = fsts  # nothing better to return
    fe.pubDate(ts)

    media_file = entry_pathogen('out', f'{profile}.{container}')

    if os.path.exists(media_file):
        u = url_maker(f'download/{feed_name}/{entry_id}.{profile}.{container}')
        fe.enclosure(u, str(os.path.getsize(media_file)), mime)


def feed(config, profile, feed_name, extra_opts, url_maker):

    #return url_maker('feed', feed_name, **extra_opts)
    def feed_pathogen(d, *r):
        return os.path.join(config['paths'][d], feed_name, *r)

    fg = feedgen.feed.FeedGenerator()
    fg.load_extension('podcast')
    fg.register_extension(
        'chapters',
        yousable.front.chapters_extensions.SimpleChaptersExtension,
        yousable.front.chapters_extensions.SimpleChaptersEntryExtension
    )

    with open(feed_pathogen('meta', 'feed.json')) as f:
        feed_info = json.load(f)

    overrides = config['feeds'][feed_name]['overrides'] or {}
    def get_overrideable(feed_info_name, overrideable_name=None):
        overrideable_name = overrideable_name or feed_info_name
        return overrides.get(overrideable_name) or feed_info[feed_info_name]

    fg.id(get_overrideable('channel_url', 'id'))
    fg.link(href=get_overrideable('channel_url', 'link'), rel='self')
    title = get_overrideable('title')
    if title.endswith(' - Videos') and not 'title' in overrides:
        title = title.removesuffix(' - Videos')
    fg.title(title)
    fg.description(get_overrideable('description') or
                   get_overrideable('title'))
    fg.podcast.itunes_author(get_overrideable('uploader'))
    t = (yousable.front.best_thumbnail.determine(feed_info)
         if not 'thumbnail' in overrides else overrides('thumbnail'))
    if t:
        fg.logo(t)

    for e in feed_info['entries']:
        generate_entry(config, profile, feed_name, url_maker, fg, e['id'],
                       lambda d, *r: feed_pathogen(d, e['id'], *r))

    return fg.rss_str(pretty=True)
