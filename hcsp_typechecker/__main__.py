"""Package entry point forwarding to the cross-platform environment doctor."""

from .doctor import main


if __name__ == "__main__":
    raise SystemExit(main())

