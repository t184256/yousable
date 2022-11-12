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
          propagatedBuildInputs = with pkgs.python3Packages; [
            flask
            flask-httpauth
            yt-dlp
            feedgen
            confuse
            requests
            fasteners
            mutagen
            ffmpeg-python
            setproctitle
          ] ++ (with pkgs; [
            ffmpeg_5-headless
          ]
          );
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
          cfg = config.services.yousable;
          system = pkgs.system;
        in {
          options.services.yousable = {
            enable = lib.mkOption {
              description = "Enable yousable service";
              type = lib.types.bool;
              default = false;
            };
            configFile = lib.mkOption {
              description = "Configuration file to use.";
              type = lib.types.str;
              default = "/etc/yousable/config.yaml";
            };
            address = lib.mkOption {
              description = "Address to listen to";
              type = lib.types.str;
              default = "127.0.0.1";
            };
            port = lib.mkOption {
              description = "Port to listen to";
              type = lib.types.int;
              default = 8080;
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
            systemd.services.yousable-back = {
              path = [ pkgs.yt-dlp pkgs.ffmpeg_5-headless ];
              description = "Podcast generator based on yt-dlp: downloader";
              wantedBy = [ "multi-user.target" ];
              after = [ "network.target" ];
              environment.YOUSABLE_CONFIG = cfg.configFile;
              serviceConfig = {
                WorkingDirectory = "/var/lib/yousable";
                ExecStart =
                  "${self.packages.${system}.yousable}/bin/yousable back";
                Restart = "on-failure";
                User = "yousable";
                Group = "yousable";
              };
            };
            systemd.services.yousable-front = {
              description = "Podcast generator based on yt-dlp: frontend";
              wantedBy = [ "multi-user.target" ];
              after = [ "network.target" ];
              environment.YOUSABLE_CONFIG = cfg.configFile;
              serviceConfig = {
                ExecStart = lib.escapeShellArgs [
                  "${self.packages.${system}.waitressEnv}/bin/waitress-serve"
                  "--threads" "12"
                  "--listen" "${cfg.address}:${builtins.toString cfg.port}"
                  "--call" "yousable.front.main:create_app"
                ];
                Restart = "on-failure";
                User = "yousable";
                Group = "yousable";
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
