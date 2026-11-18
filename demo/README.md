# Demonstration provenance

Duration: approximately 116 seconds. Silent, with readable on-screen captions.

The video is a paginated replay of actual Linux CLI outputs captured by `tools/make_demo.py`. It is not a live screen recording or a QNX-target recording. Selected finding blocks are shown in full; the complete raw outputs and executed commands are in `recorded-commands.json` and `reports/*.txt`. Intro/outro and explanatory captions are authored text.

The CLI commands run again when generating the demo; their expected exits are checked. The HTML reports were generated but not browser-interaction tested. No third-party image, music, or logo is used. Typography uses DejaVu fonts installed on the build host.

Reproduction: install Pillow and ffmpeg locally, then run `python tools/make_demo.py`. These are optional demo-production dependencies; the analyzer itself needs only Python's standard library.
