{
  lib,
  python312Packages,
  wrapGAppsHook3,
  gobject-introspection,
  pkg-config,
  gtk3,
  libappindicator-gtk3,
  wl-clipboard,
  xclip,
  libnotify,
  pipewire,
  portaudio,
  libsndfile,
  libpulseaudio,
  alsa-lib,
}:

python312Packages.buildPythonApplication rec {
  pname = "phonetic";
  version = "0.6.8";

  src = lib.cleanSource ../.;
  pyproject = true;

  build-system = [ python312Packages.setuptools ];

  dependencies = with python312Packages; [
    sounddevice
    soundfile
    numpy
    pynput
    pystray
    customtkinter
    python-dotenv
    httpx
    pillow
    packaging
    tkinter
  ];

  nativeBuildInputs = [
    wrapGAppsHook3
    gobject-introspection
    pkg-config
  ];

  buildInputs = [
    gtk3
    libappindicator-gtk3
  ];

  # Don't let wrapGAppsHook auto-wrap; we merge its args manually in preFixup
  dontWrapGApps = true;

  preFixup = ''
    makeWrapperArgs+=(
      "''${gappsWrapperArgs[@]}"
      --prefix PATH : ${lib.makeBinPath [
        wl-clipboard
        xclip
        libnotify
        pipewire
      ]}
      --prefix LD_LIBRARY_PATH : ${lib.makeLibraryPath [
        portaudio
        libsndfile
        libpulseaudio
        alsa-lib
      ]}
    )
  '';

  postInstall = ''
    mkdir -p $out/share/phonetic
    cp -r assets $out/share/phonetic/assets
  '';

  postFixup = ''
    substituteInPlace $out/lib/python3.12/site-packages/phonetic/tray.py \
      --replace-fail \
        'return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")' \
        'return "'"$out"'/share/phonetic/assets"'
  '';

  # No meaningful tests to run
  doCheck = false;

  meta = with lib; {
    description = "Hotkey-based speech-to-text via multimodal LLM";
    homepage = "https://github.com/startino/phonetic";
    license = licenses.mit;
    platforms = platforms.linux;
    mainProgram = "phonetic";
  };
}
