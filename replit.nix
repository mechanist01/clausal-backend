{ pkgs }: {
    deps = [
      pkgs.rustc
      pkgs.libiconv
      pkgs.cargo
      pkgs.python3
      pkgs.python3Packages.pip  # Changed from pkgs.pip
      pkgs.replitPackages.stderred
      # PDF dependencies
      pkgs.mupdf
      pkgs.ghostscript
      pkgs.freetype
      pkgs.zlib
      # System libraries
      pkgs.glib
      pkgs.cairo
      pkgs.pango
      pkgs.gdk-pixbuf
      # Build tools
      pkgs.pkg-config
      pkgs.gcc
    ];
    env = {
        PYTHONBIN = "${pkgs.python3}/bin/python3";
        LANG = "en_US.UTF-8";
        STDERREDBIN = "${pkgs.replitPackages.stderred}/bin/stderred";
        LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
            pkgs.mupdf
            pkgs.ghostscript
            pkgs.freetype
            pkgs.zlib
            pkgs.glib
            pkgs.cairo
            pkgs.pango
            pkgs.gdk-pixbuf
        ];
    };
}