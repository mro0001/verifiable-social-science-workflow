"""python3 -m features runs the features' command line.

PyYAML is checked before anything imports it, so a Python without it gets
the install line instead of a traceback (step S1, stuck point 2).
"""
import sys

PACKAGES_LINE = 'python3 -m pip install pyyaml "python-docx>=1.2" pytest'

try:
    import yaml  # noqa: F401
except ImportError:
    sys.stderr.write("The workflow needs PyYAML, which this Python (%s) does not have."
                     " Install it with %s\n" % (sys.executable, PACKAGES_LINE))
    sys.exit(1)

from features import cli  # noqa: E402

sys.exit(cli.main())
