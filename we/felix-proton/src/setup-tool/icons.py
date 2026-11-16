# SPDX-License-Identifier: BSD-3-Clause
"""Read PE icon resources without executing client code; decode in a bounded child."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile

MAX_IMAGE = 512 * 1024**2
MAX_ICON = 8 * 1024**2
PNG = b"\x89PNG\r\n\x1a\n"
OWNER = "Felix-Proton UU icon v1"


class IconError(RuntimeError):
    pass


class PEIcons:
    def __init__(self, image):
        self.image = image
        if image[:2] != b"MZ":
            raise IconError("客户端不是可读取图标的 PE 文件。")
        pe = self.u32(60)
        if self.bytes(pe, 4) != b"PE\0\0":
            raise IconError("客户端 PE 头无效。")
        count, optional_size = self.u16(pe + 6), self.u16(pe + 20)
        if not 1 <= count <= 96:
            raise IconError("PE 节数量无效。")
        optional = pe + 24
        magic = self.u16(optional)
        if magic not in (0x10B, 0x20B):
            raise IconError("不支持此 PE 可选头。")
        directory = 96 if magic == 0x10B else 112
        if optional_size < directory + 24 or self.u32(optional + directory - 4) < 3:
            raise IconError("PE 没有完整资源目录。")
        self.sections = []
        for index in range(count):
            section = optional + optional_size + index * 40
            self.bytes(section, 40)
            self.sections.append((self.u32(section + 12), self.u32(section + 16), self.u32(section + 20)))
        rva, size = self.u32(optional + directory + 16), self.u32(optional + directory + 20)
        if not 16 <= size <= 128 * 1024**2:
            raise IconError("PE 资源体积不受支持。")
        self.base, self.resource_size = self.rva(rva, size), size

    def bytes(self, offset, size):
        if offset < 0 or size < 0 or offset + size > len(self.image):
            raise IconError("PE 图标资源被截断或越界。")
        return self.image[offset:offset + size]

    def u16(self, offset):
        return struct.unpack("<H", self.bytes(offset, 2))[0]

    def u32(self, offset):
        return struct.unpack("<I", self.bytes(offset, 4))[0]

    def rva(self, address, size):
        candidates = [raw + address - virtual for virtual, length, raw in self.sections
                      if virtual <= address and address + size <= virtual + length]
        if len(candidates) != 1:
            raise IconError("PE 资源地址无法唯一映射到文件。")
        self.bytes(candidates[0], size)
        return candidates[0]

    def resource(self, offset, size):
        if offset < 0 or offset + size > self.resource_size:
            raise IconError("PE 资源目录偏移越界。")
        return self.bytes(self.base + offset, size)

    def entries(self, offset):
        directory = self.resource(offset, 16)
        named, ids = struct.unpack_from("<HH", directory, 12)
        if named + ids > 1024:
            raise IconError("PE 资源目录条目过多。")
        entries = self.resource(offset + 16, 8 * (named + ids))
        result = []
        for index in range(named + ids):
            key, child = struct.unpack_from("<II", entries, 8 * index)
            if key & 0x80000000:
                position = key & 0x7FFFFFFF
                length = struct.unpack("<H", self.resource(position, 2))[0]
                if not 1 <= length <= 128:
                    raise IconError("PE 图标资源名称过长。")
                key = self.resource(position + 2, length * 2).decode("utf-16-le")
            result.append((key, child & 0x7FFFFFFF, bool(child & 0x80000000)))
        return result

    def child(self, parent, key):
        matches = [entry for entry in self.entries(parent) if entry[0] == key]
        if len(matches) != 1 or not matches[0][2]:
            raise IconError("PE 缺少唯一的图标资源树。")
        return matches[0][1]

    def leaf(self, parent, preferred=None):
        entries = self.entries(parent)
        if not entries or any(entry[2] for entry in entries):
            raise IconError("PE 图标语言资源无效。")
        languages = [preferred, 2052, 1033, 0]
        entry = min(entries, key=lambda item: (languages.index(item[0]) if item[0] in languages else 99,
                                               str(item[0])))
        raw = self.resource(entry[1], 16)
        rva, size = struct.unpack_from("<II", raw)
        if not 0 < size <= MAX_ICON:
            raise IconError("PE 图标资源体积过大。")
        return self.bytes(self.rva(rva, size), size), entry[0]

    def ico(self):
        groups = self.entries(self.child(0, 14))  # RT_GROUP_ICON
        if not groups or any(not entry[2] for entry in groups):
            raise IconError("客户端没有图标组。")
        # The first group is the executable's default icon, as used by its normal shortcut.
        group, language = self.leaf(groups[0][1])
        if len(group) < 6:
            raise IconError("客户端图标组被截断。")
        reserved, kind, count = struct.unpack_from("<HHH", group)
        if reserved or kind != 1 or not 1 <= count <= 128 or len(group) < 6 + 14 * count:
            raise IconError("客户端图标组格式无效。")
        icon_tree = self.child(0, 3)  # RT_ICON
        directory, images = bytearray(struct.pack("<HHH", 0, 1, count)), []
        position = 6 + 16 * count
        for index in range(count):
            width, height, colors, reserved, planes, bits, size, resource_id = struct.unpack_from(
                "<BBBBHHIH", group, 6 + index * 14)
            image, _ = self.leaf(self.child(icon_tree, resource_id), language)
            if reserved or size != len(image) or position + size > MAX_ICON:
                raise IconError("客户端图标大小与资源不符。")
            directory.extend(struct.pack("<BBBBHHII", width, height, colors, 0, planes, bits, size, position))
            images.append(image)
            position += size
        return bytes(directory) + b"".join(images)


def extract_ico(executable):
    fd = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 64 <= before.st_size <= MAX_IMAGE:
            raise IconError("客户端文件类型或体积不受支持。")
        stream = os.fdopen(fd, "rb")
        fd = None
        with stream:
            image = stream.read(MAX_IMAGE + 1)
            after = os.fstat(stream.fileno())
            if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(image) != before.st_size):
                raise IconError("图标提取期间客户端发生变化。")
    finally:
        if fd is not None:
            os.close(fd)
    return PEIcons(image).ico(), hashlib.sha256(image).hexdigest()


def _private(path):
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise IconError("图标目录不是当前用户的私有目录。")
    return path


def _read(path, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > limit:
        raise IconError("已有品牌图标或记录的类型、归属或体积不符。")
    return path.read_bytes()


def _verify_existing(folder, source_sha, ico_sha):
    _private(folder)
    data = json.loads(_read(folder / "source.json", 4096))
    png = _read(folder / "uu.png", 4 * 1024**2)
    if (data.get("owner") != OWNER or data.get("source_sha256") != source_sha
            or data.get("ico_sha256") != ico_sha or not png.startswith(PNG)
            or data.get("png_sha256") != hashlib.sha256(png).hexdigest()):
        raise IconError("已有品牌图标发生外部改动，已保留。")
    return folder / "uu.png"


def install_icon(executable, data_home):
    ico, source_sha = extract_ico(executable)
    ico_sha = hashlib.sha256(ico).hexdigest()
    app = _private(Path(data_home) / "felix-proton-setup")
    base = _private(app / "icons-v1")
    target = base / source_sha
    if os.path.lexists(target):
        return _verify_existing(target, source_sha, ico_sha)
    with tempfile.TemporaryDirectory(prefix=".icon-", dir=base) as temporary:
        temporary = Path(temporary)
        source = temporary / "source.ico"
        source.write_bytes(ico)
        stage = temporary / "result"
        stage.mkdir(mode=0o700)
        png = stage / "uu.png"
        result = subprocess.run(["/usr/bin/python3", "-B", str(Path(__file__).resolve()),
                                 "--decode", str(source), str(png)],
                                capture_output=True, text=True, timeout=25, check=False)
        if result.returncode or not png.is_file() or not png.read_bytes().startswith(PNG):
            raise IconError("无法解码已安装 UU 的品牌图标；请保留安装现场并报告安装器版本。")
        record = {"owner": OWNER, "source_sha256": source_sha, "ico_sha256": ico_sha,
                  "png_sha256": hashlib.sha256(png.read_bytes()).hexdigest()}
        (stage / "source.json").write_text(json.dumps(record, sort_keys=True) + "\n")
        (stage / "source.json").chmod(0o600)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "native-ux"))
        from bootstrap import _rename_new, SetupError
        try:
            _rename_new(stage, target)
        except SetupError:
            if not os.path.lexists(target):
                raise
            return _verify_existing(target, source_sha, ico_sha)
    return target / "uu.png"


def _decode(source, target):
    # Parsing the PE above does not run client code. Only the extracted ICO is
    # decoded here, under memory, CPU and output limits, without a display.
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024**2, 4 * 1024**2))
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    body = Path(source).read_bytes()
    if len(body) > MAX_ICON:
        raise IconError("ICO 体积超限。")
    loader = GdkPixbuf.PixbufLoader.new_with_type("ico")
    loader.set_size(256, 256)
    loader.write(body)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf is None or not 0 < pixbuf.get_width() <= 256 or not 0 < pixbuf.get_height() <= 256:
        raise IconError("ICO 没有受支持的画面。")
    success, png = pixbuf.save_to_bufferv("png", [], [])
    if not success:
        raise IconError("ICO 无法输出 PNG。")
    with Path(target).open("xb") as output:
        output.write(png)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--decode":
        sys.exit("此模块由安装器内部调用。")
    _decode(sys.argv[2], sys.argv[3])
