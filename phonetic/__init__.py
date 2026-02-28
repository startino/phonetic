from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("phonetic")
except PackageNotFoundError:
    __version__ = "0.0.0"  # fallback for development without install
