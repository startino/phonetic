#!/usr/bin/env fish

set -l gcc_lib (nix eval --raw 'nixpkgs#legacyPackages.x86_64-linux.stdenv.cc.cc.lib')
set -gx LD_LIBRARY_PATH "$gcc_lib/lib":$LD_LIBRARY_PATH
