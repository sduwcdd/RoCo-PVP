"""Build the local Windows app entry using the installed .NET compiler and DiMo asset.

The resulting EXE belongs in this project root; it reuses overlay/Electron and the project venv.
"""
from pathlib import Path
import os
import subprocess
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]


def main():
    compiler = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        raise RuntimeError("Installed Windows .NET Framework compiler is missing")
    icon = ROOT / "overlay/dimo.ico"
    source = ROOT / "web/assets/roco/pet-avatars/3004.png"
    image = ImageOps.pad(Image.open(source).convert("RGBA"), (256, 256), color=(0, 0, 0, 0))
    image.save(icon, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    output = ROOT / "洛克PVP.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/optimize+", "/reference:System.Windows.Forms.dll",
                    "/win32icon:" + str(icon), "/out:" + str(output), str(ROOT / "overlay/Launcher.cs")], check=True)
    if not output.is_file() or output.stat().st_size < 4096:
        raise RuntimeError("No valid executable was produced")
    print(str(output))


if __name__ == "__main__":
    main()
