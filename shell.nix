{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    yt-dlp
    ffmpeg
    (python3.withPackages (ps: with ps; [
      flask
      feedgen
      cachetools
      confuse
      requests
      fasteners
      mutagen
      ffmpeg
    ]))
  ];
  nativeBuildInputs = with pkgs.python3Packages; [
    coverage
    flake8
    flake8-import-order
    codespell
  ];
}
