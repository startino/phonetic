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
        Path to an environment file containing the OPENROUTER_API_KEY secret.
        This file is passed as EnvironmentFile to the systemd service. App
        toggles live in settings.json and per-hotkey transcription in
        profiles.json (both in the config dir); only the secret needs to be
        provided here.
      '';
      example = "/home/user/.config/phonetic/.env";
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
        # Prefix with "-" so a missing env file is non-fatal. The app also reads
        # its key directly from .env / config.env in the config dir, so a missing
        # EnvironmentFile must NOT block startup (otherwise the service can crash
        # with Result=resources before ever exec'ing — e.g. if the file was
        # renamed and the new one doesn't exist yet).
        EnvironmentFile = "-" + cfg.environmentFile;
      };
    };
  };
}
