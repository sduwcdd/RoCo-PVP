"""Stage trusted local iOS artifacts; never download or substitute desktop wheels."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import py_compile
import shutil
import sys

IOS = Path(__file__).resolve().parents[1]
REPO = IOS.parents[1]


def copy(source, destination):
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-xcframework", type=Path, required=True)
    parser.add_argument("--packages-device", type=Path, required=True,
                        help="Python 3.13 iOS arm64 packages, including native cryptography/Crypto modules")
    parser.add_argument("--packages-simulator", type=Path, required=True,
                        help="Python 3.13 iOS simulator packages matching the selected simulator architecture")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 13):
        parser.error("Run with Python 3.13 to verify bytecode magic")
    generated = REPO / "mobile/build/generated"
    manifest = json.loads((generated / "manifest.json").read_text(encoding="utf8"))
    archive = generated / "assets/resources.rpk"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["resource_sha256"]:
        raise ValueError("Resource hash differs from generated manifest")
    for module in (generated / "python").rglob("*.pyc"):
        if module.read_bytes()[:4] != importlib.util.MAGIC_NUMBER:
            raise ValueError(f"Python 3.13 bytecode required: {module}")
    framework = args.python_xcframework.resolve()
    metadata = plistlib.loads((framework / "Info.plist").read_bytes())
    slices = {entry["LibraryIdentifier"]: entry for entry in metadata["AvailableLibraries"]
              if entry.get("SupportedPlatform") == "ios"}
    device = [key for key, value in slices.items() if value.get("SupportedPlatformVariant") != "simulator"]
    simulator = [key for key, value in slices.items() if value.get("SupportedPlatformVariant") == "simulator"]
    if len(device) != 1 or len(simulator) != 1:
        raise ValueError("Expected one iOS device slice and one simulator slice in Python.xcframework")
    for key in device + simulator:
        if not (framework / key / "lib/python3.13/encodings/__init__.py").exists():
            raise ValueError(f"Python 3.13 standard library missing from {key}/lib")
    for folder in (args.packages_device, args.packages_simulator):
        if not folder.is_dir() or not all((folder / name).is_dir() for name in ("cryptography", "Crypto", "scapy", "msgpack", "google/protobuf")):
            raise ValueError(f"Incomplete iOS app_packages directory: {folder}")
    runtime = IOS / "Runtime"
    if runtime.exists():
        raise FileExistsError("Runtime already exists; move it aside before preparing a different build")
    temporary = IOS / "Runtime.preparing"
    temporary.mkdir()
    try:
        copy(framework, temporary / "Python.xcframework")
        copy(generated / "python", temporary / "engine")
        py_compile.compile(str(IOS / "RocoLocal/roco_ios_bootstrap.py"),
            cfile=str(temporary / "engine/roco_ios_bootstrap.pyc"),
            dfile="roco_ios_bootstrap.py", doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        copy(archive, temporary / "resources.rpk")
        copy(args.packages_device, temporary / "packages/iphoneos")
        copy(args.packages_simulator, temporary / "packages/iphonesimulator")
        report = {"device_slice": device[0], "simulator_slice": simulator[0], "engine": manifest}
        (temporary / "prepared.json").write_text(json.dumps(report, indent=2), encoding="utf8")
        temporary.rename(runtime)
    except BaseException:
        shutil.rmtree(temporary)
        raise
    print("Prepared Runtime/; native dependencies still require Xcode build and on-device import verification.")


if __name__ == "__main__":
    main()
