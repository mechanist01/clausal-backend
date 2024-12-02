{ pkgs }: {
    deps = [
      pkgs.rustc
      pkgs.libiconv
      pkgs.cargo
      pkgs.python3Full
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
        PYTHONBIN = "${pkgs.python310Full}/bin/python3.9";
        LANG = "en_US.UTF-8";
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