"""Package entry point forwarding to the cross-platform environment doctor."""

from .tooling.doctor import main


if __name__ == "__main__":
    raise SystemExit(main())
