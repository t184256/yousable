{
  description = "automated downloader / podcast feed generator based on yt-dlp";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs";

  outputs = { self, nixpkgs, flake-utils }@inputs:
    let
      pyDeps = pyPackages: with pyPackages; [
        yt-dlp
        flask
        flask-httpauth
        feedgen
        feedparser
        confuse
        requests
        mutagen
        ffmpeg-python
        setproctitle
        pytz
      ];

      nativeDeps = pkgs: with pkgs; [
        ffmpeg_7-headless
      ];

      yousable-package = {pkgs, python3Packages}:
        python3Packages.buildPythonPackage {
          pname = "yousable";
          version = "0.0.1";
          src = ./.;
          propagatedBuildInputs = (pyDeps python3Packages) ++ (nativeDeps pkgs);
          doCheck = false;
        };

      overlay-yousable = final: prev: {
        pythonPackagesExtensions =
          prev.pythonPackagesExtensions ++ [(pyFinal: pyPrev: {
            yousable = final.callPackage yousable-package {
              python3Packages = pyFinal;
            };
          })];
      };

      overlay-all = nixpkgs.lib.composeManyExtensions [
        overlay-yousable
      ];

    in

      flake-utils.lib.eachDefaultSystem (system:
        let
          pkgs = import nixpkgs { inherit system; overlays = [ overlay-all ]; };
          defaultPython3Packages = pkgs.python3Packages;

          yousable = defaultPython3Packages.yousable;
          app = flake-utils.lib.mkApp {
            drv = yousable;
            exePath = "/bin/yousable";
          };
        in
        {
          devShells.default = pkgs.mkShell {
            buildInputs = [(defaultPython3Packages.python.withPackages pyDeps)];
            nativeBuildInputs = [(pkgs.buildEnv {
              name = "yousable-env";
              pathsToLink = [ "/bin" ];
              paths = nativeDeps pkgs;
            })];
          };
          packages.yousable = yousable;
          packages.default = yousable;
          apps.yousable = app;
          apps.default = app;
        }

    ) // (

      {
        overlays.yousable = overlay-yousable;
        overlays.default = overlay-all;
      }

    ) // (
    let
      nixosModule = { config, lib, pkgs, ... }:
        let
          inherit (pkgs) system;
          cfg = config.services.yousable;
          bin_yousable = "${cfg.package}/bin/yousable";
          waitressEnv = pkgs.python3.withPackages (p: with p; [
            waitress cfg.package
          ]);
        in {
          options.services.yousable = {
            enable = lib.mkOption {
              description = "Enable yousable in general";
              type = lib.types.bool;
              default = false;
            };
            package = lib.mkOption {
              description = "yousable package to use";
              type = lib.types.package;
              default = self.packages.${system}.yousable;
            };
            crawler.enable = lib.mkOption {
              description = "Enable yousable crawler service";
              type = lib.types.bool;
              default = true;
            };
            downloader.enable = lib.mkOption {
              description = "Enable yousable downloader service";
              type = lib.types.bool;
              default = true;
            };
            #streamer.enable = lib.mkOption {
            #  description = "Enable yousable streamer service";
            #  type = lib.types.bool;
            #  default = true;
            #};
            #splitter.enable = lib.mkOption {
            #  description = "Enable yousable splitter service";
            #  type = lib.types.bool;
            #  default = true;
            #};
            #cleaner.enable = lib.mkOption {
            #  description = "Enable yousable cleaner service";
            #  type = lib.types.bool;
            #  default = true;
            #};
            server.enable = lib.mkOption {
              description = "Enable yousable server service";
              type = lib.types.bool;
              default = true;
            };
            server.address = lib.mkOption {
              description = "Address to listen to";
              type = lib.types.str;
              default = "127.0.0.1";
            };
            server.port = lib.mkOption {
              description = "Port to listen to";
              type = lib.types.int;
              default = 8080;
            };
            configFile = lib.mkOption {
              description = "Configuration file to use.";
              type = lib.types.str;
              default = "/etc/yousable/config.yaml";
            };
          };
          config = lib.mkIf cfg.enable {
            users = {
              users.yousable.home = "/var/lib/yousable";
              users.yousable.createHome = true;
              users.yousable.isSystemUser = true;
              users.yousable.group = "yousable";
              groups.yousable = {};
            };
            systemd.services = {
              yousable-crawler = lib.mkIf cfg.crawler.enable {
                description = "Podcast generator based on yt-dlp: crawler";
                wantedBy = [ "multi-user.target" ];
                after = [ "network.target" ];
                environment.YOUSABLE_CONFIG = cfg.configFile;
                serviceConfig = {
                  WorkingDirectory = "/var/lib/yousable";
                  ExecStart = "${bin_yousable} crawler";
                  Restart = "on-failure";
                  User = "yousable";
                  Group = "yousable";
                };
              };
              yousable-downloader = lib.mkIf cfg.downloader.enable {
                path = [ pkgs.ffmpeg_7-headless ];
                description = "Podcast generator based on yt-dlp: downloader";
                wantedBy = [ "multi-user.target" ];
                after = [ "network.target" ];
                environment.YOUSABLE_CONFIG = cfg.configFile;
                serviceConfig = {
                  WorkingDirectory = "/var/lib/yousable";
                  ExecStart = "${bin_yousable} downloader";
                  Restart = "on-failure";
                  User = "yousable";
                  Group = "yousable";
                };
              };
              # TODO: streamer
              # TODO: splitter
              # TODO: cleaner
              yousable-server = lib.mkIf cfg.server.enable {
                description = "Podcast generator based on yt-dlp: server";
                wantedBy = [ "multi-user.target" ];
                after = [ "network.target" ];
                environment.YOUSABLE_CONFIG = cfg.configFile;
                serviceConfig = {
                  ExecStart = lib.escapeShellArgs [
                    "${waitressEnv}/bin/waitress-serve"
                    "--threads" "12"
                    "--listen"
                    "${cfg.server.address}:${builtins.toString cfg.server.port}"
                    "--call" "yousable.front.main:create_app"
                  ];
                  Restart = "on-failure";
                  User = "yousable";
                  Group = "yousable";
                };
              };
            };
          };
        };
      in
      {
        inherit nixosModule;
        nixosModules = { yousable = nixosModule; default = nixosModule; };
      }
    );
}
