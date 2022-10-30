# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import feedgen.ext.base
from feedgen.util import xml_elem


def strtime(seconds):  # 3603.45 -> `01:00:03.45`
    seconds = round(seconds)
    s = ''
    if seconds > 3600:
        h, seconds = seconds // 3600, seconds % 3600
        s += f'{h}:'
    if seconds > 60:
        m, seconds = seconds // 60, seconds % 60
        s += f'{m:02d}:'
    if seconds == int(seconds):
        seconds = int(seconds)
    s += f'{seconds:02d}'
    return s


class SimpleChaptersExtension(feedgen.ext.base.BaseExtension):
    PSC_NS = 'http://podlove.org/simple-chapters'

    @classmethod
    def extend_ns(cls):
        return {'psc': cls.PSC_NS}


class SimpleChaptersEntryExtension(feedgen.ext.base.BaseEntryExtension):
    PSC_NS = 'http://podlove.org/simple-chapters'

    def __init__(self):
        self.__psc_chapters = []

    def add(self, start, title):  # link and url not implementend
        self.__psc_chapters.append({'start': strtime(start), 'title': title})

    def extend_rss(self, entry):
        if self.__psc_chapters:
            chapters = xml_elem(f'{{{self.PSC_NS}}}chapters', entry)
            for e in self.__psc_chapters:
                chapter = xml_elem(f'{{{self.PSC_NS}}}chapter', chapters)
                for k, v in e.items():
                    chapter.attrib[k] = str(v)
        return entry
