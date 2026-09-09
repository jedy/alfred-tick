"""Build the installable workflow from an explicit, credential-free file list."""

from pathlib import Path
import plistlib
import zipfile

FILES = (
    "tick.py",
    "info.plist",
    "icon.png",
    "2701BB9E-9DD0-4435-B2DF-F09A050D90C4.png",
    "5034F630-C7DA-4514-9B9E-8ECE1BFD7870.png",
)


def main():
    root = Path(__file__).resolve().parent
    version = plistlib.loads((root / "info.plist").read_bytes())["version"]
    output = root / (f"滴答清单 v{version}.alfredworkflow")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(root / name, name)
    print(output)


if __name__ == "__main__":
    main()
