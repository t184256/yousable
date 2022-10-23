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
    CONFIG_FEED_DEFAULTS = {
        'load_entries': int,
        'keep_entries': int,
        'poll_seconds': int,
        'profiles': confuse.Sequence(str),
        'sponsorblock_remove': confuse.Sequence(confuse.Choice(SPONSORBLOCKS)),
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
        'load_entries': confuse.Optional(feed_defaults['load_entries']),
        'keep_entries': confuse.Optional(feed_defaults['keep_entries']),
        'poll_seconds': confuse.Optional(feed_defaults['poll_seconds']),
        'profiles': \
                confuse.Optional(confuse.Sequence(profile_names),
                                 default=feed_defaults['profiles']),
        'sponsorblock_remove': \
                confuse.Optional(SPONSORBLOCKS,
                                 default=feed_defaults['sponsorblock_remove']),
    }

    config_template = {
        'paths': {
            'tmp': confuse.Filename(),
            'out': confuse.Filename(),
            'meta': confuse.Filename(),
        },
        'profiles': confuse.MappingValues({
            'download': dict,
        }),
        'feeds': confuse.MappingValues(config_template_feed),
    }

    print('effective config:', file=sys.stderr)
    cfg = config.get(config_template)
    pp = pprint.PrettyPrinter(indent=2, stream=sys.stderr)
    pp.pprint(cfg)
    return cfg


def main():
    if len(sys.argv) == 2:
        subcommand = sys.argv[1]
        config = load_config()
        if subcommand == 'back':
            return yousable.back.main.main(config)
        elif subcommand == 'front':
            return yousable.front.main.main(config)
    print('Usage: yousable {back|front}', file=sys.stderr)
    if not os.getenv('YOUSABLE_CONFIG'):
        print('Config can be supplied with YOUSABLE_CONFIG variable.',
              file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
