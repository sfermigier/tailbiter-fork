import sys

from .compiler import load_file


def main():
    sys.argv.pop(0)
    load_file(sys.argv[0], "__main__")


if __name__ == "__main__":
    main()
