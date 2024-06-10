{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    yt-dlp
    ffmpeg_5-headless
    (python3.withPackages (ps: with ps; [
      flask
      flask-httpauth
      feedgen
      confuse
      requests
      mutagen
      ffmpeg-python
      setproctitle
      pytz
    ]))
  ];
  nativeBuildInputs = (with pkgs.python3Packages; [
    coverage
    flake8
    flake8-import-order
  ]) ++ (with pkgs; [
    codespell
  ]);
}
