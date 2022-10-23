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
            yt-dlp
            feedgen
            confuse
            cachetools
            requests
            fasteners
            mutagen
            ffmpeg
          ] ++ (with pkgs; [
            ffmpeg
          ]);
          doCheck = false;
        };
        waitressEnv = pkgs.python3.withPackages (p: with p; [
          waitress yousable.front
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
              users.yousable.isSystemUser = true;
              users.yousable.group = "yousable";
              groups.yousable = {};
            };
            systemd.services.yousable = {
              path = [ pkgs.yt-dlp-light ];  # move to wrapper?
              description = "Podcast generator based on yt-dlp";
              wantedBy = [ "multi-user.target" ];
              after = [ "network.target" ];
              environment.PODCASTIFY_CONFIG = cfg.configFile;
              serviceConfig = {
                ExecStart = lib.escapeShellArgs [
                  "${self.packages.${system}.waitressEnv}/bin/waitress-serve"
                  "--threads" "16"
                  "--listen" "${cfg.address}:${builtins.toString cfg.port}"
                  "yousable.main:app"
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
