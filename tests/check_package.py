"""Guard against the ICU dependency collision seen in the shipped EXE."""
from pathlib import Path
import sys

from PyInstaller.archive.readers import CArchiveReader


def check(path):
    archive = CArchiveReader(str(path))
    # This pinned Qt Windows build uses the Windows ICU API, not a tool's ICU.
    collisions = [name for name in archive.toc
                  if Path(name).name.casefold() in ("icuuc.dll", "icuin.dll", "icudt.dll")]
    if collisions:
        raise RuntimeError(f"打包混入了可能与 Windows ICU 冲突的 DLL：{collisions}")
    if "update_install.ps1" not in archive.toc:
        raise RuntimeError("打包缺少覆盖安装所需的 update_install.ps1。")
    print(f"打包依赖检查通过：{path}")


if __name__ == "__main__":
    check(Path(sys.argv[1]))
