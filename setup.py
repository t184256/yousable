# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

from setuptools import setup

setup(
    name='yousable',
    version='0.0.1',
    url='https://github.com/t184256/yousable',
    author='Alexander Sosedkin',
    author_email='monk@unboiled.info',
    description="youtube downloader / podcast feed generator based on yt-dlp",
    packages=[
        'yousable',
        'yousable.back',
        'yousable.front',
    ],
    install_requires=[
        'flask',
        'feedgen',
        'requests',
        'confuse',
        'mutagen',
        'ffmpeg-python',
        'setproctitle',
        'pytz',
    ],
    entry_points={
        'console_scripts': [
            'yousable = yousable.main:main',
        ],
    },
)
