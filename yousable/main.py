# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys
import pprint

import confuse

import yousable
import yousable.sponsorblock


def load_config():
    SPONSORBLOCKS = confuse.Sequence(confuse.Choice(
        list(yousable.sponsorblock.CATEGORIES)
    ))
    CONTAINER_CHOICES = (
        'avi', 'flv', 'mkv', 'mov', 'mp4', 'webm', 'aac', 'aiff', 'alac',
        'flac', 'm4a', 'mka', 'mp3', 'ogg', 'opus', 'vorbis', 'wav'
    )
    CONFIG_FEED_DEFAULTS = {
        'load_entries': int,
        'keep_entries': int,
        'keep_entries_seconds': int,
        'poll_seconds': int,
        'profiles': confuse.Sequence(str),
        'sponsorblock_remove': confuse.Sequence(confuse.Choice(SPONSORBLOCKS)),
        'live_slice_seconds': int,
    }

    config = confuse.Configuration('yousable', __name__)
    print('configuration directory is', config.config_dir(), file=sys.stderr)
    custom_config = os.getenv('YOUSABLE_CONFIG')
    if custom_config:
        print(f'YOUSABLE_CONFIG={custom_config}', file=sys.stderr)
        config.set_file(custom_config)
    feed_defaults = config.get({'feed_defaults': CONFIG_FEED_DEFAULTS})
    feed_defaults = feed_defaults['feed_defaults']
    profile_names = confuse.Choice(config.get()['profiles'].keys())

    config_template_feed = {
        'url': str,
        'extra_urls': confuse.Optional(confuse.Sequence(str)),
        'poll_rss_urls': confuse.Optional(confuse.Sequence(str)),
        'load_entries': confuse.Optional(feed_defaults['load_entries']),
        'keep_entries': confuse.Optional(feed_defaults['keep_entries']),
        'keep_entries_seconds': \
                confuse.Optional(feed_defaults['keep_entries_seconds']),
        'poll_seconds': confuse.Optional(feed_defaults['poll_seconds']),
        'profiles': \
                confuse.Optional(confuse.Sequence(profile_names),
                                 default=feed_defaults['profiles']),
        'sponsorblock_remove': \
                confuse.Optional(SPONSORBLOCKS,
                                 default=feed_defaults['sponsorblock_remove']),
        'overrides': confuse.Optional(dict),
        'live_slice_seconds': \
                confuse.Optional(feed_defaults['live_slice_seconds']),
    }

    config_template = {
        'secrets': confuse.OneOf([None, confuse.MappingValues(str)]),
        'paths': {
            'tmp': confuse.Filename(),
            'out': confuse.Filename(),
            'live': confuse.Optional(confuse.Filename()),
            'meta': confuse.Filename(),
            'x_accel': confuse.Optional(confuse.Filename()),
        },
        'limits': {
            'throttle_seconds': int,
            'throttle_variance_seconds': int,
            'throttle_extra_seconds': int,
            'throttle_rss_seconds': int,
        },
        'profiles': confuse.MappingValues({
            'container': confuse.Choice(CONTAINER_CHOICES),
            'video': confuse.Choice([True, False], default=True),
            'download': dict,
            'live': confuse.Optional({
                'audio': confuse.Optional(dict, default={}),
                'video': confuse.Optional(dict, default={}),
            }),
        }),
        'feeds': confuse.MappingValues(config_template_feed),
        'yt_dlp_options': {
            'all': confuse.Optional(dict, default={}),
        },
    }

    print('effective config:', file=sys.stderr)
    cfg = config.get(config_template)
    pp = pprint.PrettyPrinter(indent=2, stream=sys.stderr)
    pp.pprint(cfg)
    return cfg


def main():
    if len(sys.argv) == 2:
        subcommand = sys.argv[1]
        if subcommand == 'crawler':
            return yousable.back.crawler.main(load_config())
        elif subcommand == 'downloader':
            return yousable.back.downloader.main(load_config())
        elif subcommand == 'streamer':
            return yousable.back.streamer.main(load_config())
        elif subcommand == 'splitter':
            return yousable.back.splitter.main(load_config())
        elif subcommand == 'cleaner':
            return yousable.back.cleaner.main(load_config())
        elif subcommand == 'server':
            return yousable.front.main.main()
        elif subcommand == 'hash':
            print(yousable.front.main.hash_password(input('password> ')))
    print('Usage: yousable '
          '{crawler|downloader|streamer|splitter|cleaner|server|hash}',
          file=sys.stderr)
    if not os.getenv('YOUSABLE_CONFIG'):
        print('Config can be supplied with YOUSABLE_CONFIG variable.',
              file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
