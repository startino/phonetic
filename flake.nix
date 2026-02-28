{
  description = "Dev shell for phonetic with uv and system libs (NumPy, PortAudio, libsndfile, tkinter, pystray)";

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
          pkgs.gobject-introspection
          pkgs.gtk3
          pkgs.libappindicator-gtk3
          pkgs.tcl
          pkgs.tk
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
            pkgs.wl-clipboard
            pkgs.xorg.libX11
            pkgs.xorg.libXext
            pkgs.xorg.libXrender
            pkgs.pkg-config
            pkgs.gobject-introspection
            pkgs.gtk3
            pkgs.libappindicator-gtk3
            pkgs.python312Packages.tkinter
            pkgs.tcl
            pkgs.tk
            pkgs.linuxHeaders
          ];

          shellHook = ''
            export LD_LIBRARY_PATH=${libPath}:$LD_LIBRARY_PATH
            export C_INCLUDE_PATH="${pkgs.linuxHeaders}/include''${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
            export GI_TYPELIB_PATH="${pkgs.libappindicator-gtk3}/lib/girepository-1.0:${pkgs.gtk3}/lib/girepository-1.0:${pkgs.glib}/lib/girepository-1.0''${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
            echo "phonetic dev shell: LD_LIBRARY_PATH prepared for NumPy/PortAudio/libsndfile/tkinter/pystray"
            echo "Use: uv pip install -e . | cat && uv run phonetic | cat"
          '';
        };
      });
    };
}
