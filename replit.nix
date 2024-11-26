{ pkgs }: {
  deps = [
    pkgs.python39
    pkgs.python39Packages.pip
    pkgs.mupdf
    pkgs.zlib
    pkgs.glib
    pkgs.pkg-config
    pkgs.cairo
    pkgs.gobject-introspection
  ];
  env = {
    PYTHONBIN = "${pkgs.python39}/bin/python3.9";
    LANG = "en_US.UTF-8";
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      pkgs.mupdf
      pkgs.zlib
      pkgs.glib
      pkgs.cairo
    ];
  };
}