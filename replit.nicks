{ pkgs }: {
    deps = [
        pkgs.python310Full
        pkgs.pip
        pkgs.replitPackages.prybar-python310
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
        PYTHONBIN = "${pkgs.python310Full}/bin/python3.10";
        LANG = "en_US.UTF-8";
        STDERREDBIN = "${pkgs.replitPackages.stderred}/bin/stderred";
        PRYBAR_PYTHON_BIN = "${pkgs.replitPackages.prybar-python310}/bin/prybar-python310";
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