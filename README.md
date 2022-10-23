# yousable

A Flask app that monitors and downloads Youtube channels/playlists,
subsequently exporting them as podcast feeds.
Probably supports other services that
[yt-dlp](https://github.com/yt-dlp/yt-dlp) can handle.

Sounds similar to [podsync](https://github.com/mxpv/podsync),
except it doesn't need a YouTube API token.

Is an evolution of [podcastify](https://github.com/t184256/podcastify),
except it supports:

* live stream recording and restreaming
* cutting out sponsor ads and more
  using [Sponsorblock](https://sponsor.ajay.app)

at the cost of requiring gigabytes of disk space where podcastify needed none.

See `config.yml` to get an idea of what's supported.
