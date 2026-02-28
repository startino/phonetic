"""Backward-compatibility shim. Delegates to phonetic.__main__:main."""
from phonetic.__main__ import main

if __name__ == "__main__":
    main()
