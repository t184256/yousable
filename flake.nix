{
  description = "automated downloader / podcast feed generator based on yt-dlp";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  #inputs.nixpkgs.url = "github:NixOS/nixpkgs";

  outputs = { self, nixpkgs, flake-utils }:
    (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        yousable = pkgs.python3Packages.buildPythonPackage {
          pname = "yousable";
          version = "0.0.1";
          src = ./.;
          propagatedBuildInputs = (with pkgs.python3Packages; [
            yt-dlp
            flask
            flask-httpauth
            feedgen
            confuse
            requests
            mutagen
            ffmpeg-python
            setproctitle
            pytz
          ]) ++ (with pkgs; [
            ffmpeg_7-headless
          ]);
          doCheck = false;
        };
        waitressEnv = pkgs.python3.withPackages (p: with p; [
          waitress yousable
        ]);
        app = flake-utils.lib.mkApp { drv = yousable; };
      in
      {
        packages.yousable = yousable;
        packages.waitressEnv = waitressEnv;
        defaultPackage = yousable;
        apps.yousable = app;
        defaultApp = app;
        devShell = import ./shell.nix { inherit pkgs; };
      }
    )) // (
    let
      nixosModule = { config, lib, pkgs, ... }:
        let
          inherit (pkgs) system;
          cfg = config.services.yousable;
          bin_yousable = "${self.packages.${system}.yousable}/bin/yousable";
        in {
          options.services.yousable = {
            enable = lib.mkOption {
              description = "Enable yousable in general";
              type = lib.types.bool;
              default = false;
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
                    "${self.packages.${system}.waitressEnv}/bin/waitress-serve"
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
