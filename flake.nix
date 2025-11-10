{
  description = "Dev shell for phonetic with uv and system libs (NumPy, PortAudio, libsndfile)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
    in {
      devShells = forAllSystems (pkgs: let
        libPath = pkgs.lib.makeLibraryPath [
          pkgs.stdenv.cc.cc.lib
          pkgs.portaudio
          pkgs.libsndfile
          pkgs.alsaLib
          pkgs.libpulseaudio
          pkgs.xorg.libX11
          pkgs.xorg.libXext
          pkgs.xorg.libXrender
        ];
      in {
        default = pkgs.mkShell {
          packages = [
            pkgs.uv
            pkgs.stdenv.cc.cc
            pkgs.portaudio
            pkgs.libsndfile
            pkgs.alsaLib
            pkgs.libpulseaudio
            pkgs.xclip
            pkgs.xorg.libX11
            pkgs.xorg.libXext
            pkgs.xorg.libXrender
            pkgs.pkg-config
          ];

          shellHook = ''
            export LD_LIBRARY_PATH=${libPath}:$LD_LIBRARY_PATH
            echo "phonetic dev shell: LD_LIBRARY_PATH prepared for NumPy/PortAudio/libsndfile"
            echo "Use: uv pip install -e . | cat && uv run phonetic | cat"
          '';
        };
      });
    };
}


