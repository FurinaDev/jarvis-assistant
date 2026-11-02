'''`python -m jarvis` ile başlatır.'''

import sys
if sys.platform != 'win32':
    from .app import main
    sys.exit(main())
try:
    from .ui import win_window
    if not win_window.single_instance():
        from .log import log
        log('JARVIS zaten açık: var olan pencere öne getirildi')
        sys.exit(0)
    if sys.stderr is None:
        win_window.attach_streams()
    from .app import main
    code = main()
except Exception:
    from .ui.win_window import fatal
    fatal()
    code = 1
sys.exit(code)
