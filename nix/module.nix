{ config, lib, pkgs, ... }:

let
  cfg = config.services.phonetic;
in {
  options.services.phonetic = {
    enable = lib.mkEnableOption "Phonetic speech-to-text service";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.phonetic;
      defaultText = lib.literalExpression "pkgs.phonetic";
      description = "The Phonetic package to use.";
    };

    environmentFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Path to an environment file containing configuration (e.g. OPENROUTER_API_KEY).
        This file is passed as EnvironmentFile to the systemd service.
      '';
      example = "/home/user/.config/phonetic/config.env";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.phonetic = {
      description = "Phonetic speech-to-text";
      after = [ "graphical-session.target" ];
      wantedBy = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${cfg.package}/bin/phonetic --headless";
        Restart = "on-failure";
        RestartSec = 2;
        Environment = [ "PYTHONUNBUFFERED=1" ];
      } // lib.optionalAttrs (cfg.environmentFile != null) {
        EnvironmentFile = cfg.environmentFile;
      };
    };
  };
}
