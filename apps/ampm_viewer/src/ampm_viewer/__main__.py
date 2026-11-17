# Lets `python -m ampm_viewer`, the `ampm-viewer` script and the packaged
# app share one entry point.
#
# The packaged app is also how a DBSCAN job runs in its own process
# (``--dbscan-job <job.json>``, see dbscan_job.py): that switch is handled
# here, before any of the Qt app loads.
#
# Absolute (not relative) imports: PyInstaller runs this file as the
# top-level ``__main__`` script, which has no parent package, so ``from .shell
# …`` would fail with "attempted relative import with no known parent
# package". The absolute form resolves the bundled package and works equally
# for ``python -m ampm_viewer`` and the ``ampm-viewer`` console script.
if __name__ == "__main__":
    import sys

    from ampm_viewer import dbscan_job

    if len(sys.argv) > 1 and sys.argv[1] == dbscan_job.FLAG:
        sys.exit(dbscan_job.main(sys.argv[2:]))

    from ampm_viewer.shell.app import main

    main()
