{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    yt-dlp
    ffmpeg
    (python3.withPackages (ps: with ps; [
      flask
      flask-httpauth
      feedgen
      confuse
      requests
      fasteners
      mutagen
      ffmpeg-python
      setproctitle
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
