"""Xcode build phase: copy selected iOS runtime, framework-package .so and sign."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess


def install():
    project = Path(os.environ["PROJECT_DIR"])
    bundle = Path(os.environ["TARGET_BUILD_DIR"]) / os.environ["WRAPPER_NAME"]
    runtime = project / "Runtime"
    prepared = json.loads((runtime / "prepared.json").read_text(encoding="utf8"))
    platform = os.environ["PLATFORM_NAME"]
    if platform not in ("iphoneos", "iphonesimulator"):
        raise ValueError("Only iOS device/simulator supported")
    selected = prepared["simulator_slice" if platform == "iphonesimulator" else "device_slice"]
    # These are generated app-bundle paths, never original source inputs.
    for name, source in (("python/lib", runtime / "Python.xcframework" / selected / "lib"),
                         ("engine", runtime / "engine"),
                         ("app_packages", runtime / "packages" / platform)):
        destination = bundle / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    shutil.copy2(runtime / "resources.rpk", bundle / "resources.rpk")
    frameworks = bundle / "Frameworks"
    frameworks.mkdir(exist_ok=True)
    # CPython's documented AppleFrameworkLoader resolves these .fwork markers.
    for base in (bundle / "python/lib/python3.13/lib-dynload", bundle / "app_packages"):
        for binary in base.rglob("*.so"):
            relative = binary.relative_to(base)
            module = ".".join(relative.parts[:-1] + (relative.name.split(".")[0],))
            folder = frameworks / (module + ".framework")
            folder.mkdir(exist_ok=True)
            executable = folder / module
            shutil.move(str(binary), str(executable))
            metadata = {"CFBundleExecutable": module, "CFBundleIdentifier":
                        os.environ["PRODUCT_BUNDLE_IDENTIFIER"] + "." + module.replace("_", "-"),
                        "CFBundlePackageType": "FMWK", "CFBundleVersion": "1",
                        "CFBundleShortVersionString": "1.0", "MinimumOSVersion": "16.0"}
            (folder / "Info.plist").write_bytes(plistlib.dumps(metadata))
            marker = binary.with_suffix(".fwork")
            marker.write_text(executable.relative_to(bundle).as_posix(), encoding="utf8")
            (folder / (module + ".origin")).write_text(marker.relative_to(bundle).as_posix(), encoding="utf8")
            if os.environ.get("CODE_SIGNING_ALLOWED") != "NO":
                identity = os.environ.get("EXPANDED_CODE_SIGN_IDENTITY") or "-"
                subprocess.run(["/usr/bin/codesign", "--force", "--sign", identity,
                    "--timestamp=none", str(folder)], check=True)


if __name__ == "__main__":
    install()
