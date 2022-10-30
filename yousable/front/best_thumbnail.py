# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

def determine(info):
    def ratio(t):
        if t['width'] > t['height']:
            return t['width'] / t['height']
        else:
            return t['height'] / t['width']

    if 'thumbnails' in info:
        t = info['thumbnails'][0]
        thumbnails = [t for t in info['thumbnails']
                      if 'width' in t and 'height' in t]
        if thumbnails:
            best_thumbnail = thumbnails[0]
            for t in thumbnails:
                # take the most squarish thumbnail of of them all...
                if 1 <= ratio(t) <= ratio(best_thumbnail):
                    # ... and the largest one among the equally squarish
                    if (ratio(t) == ratio(best_thumbnail) and
                            t['width'] <= best_thumbnail['width']):
                        continue
                    best_thumbnail = t
            return best_thumbnail['url']
