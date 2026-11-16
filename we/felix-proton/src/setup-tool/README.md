# Felix-Proton 首次安装引导

此目录提供首次安装入口，复用相邻 `native-ux/` 的固定运行器校验、专用前缀初始化、Windows UU 安装和原 Steam/UU 图标接入，不复制或放宽底层校验。

设计边界：

- `check` 只检查本机依赖和可选官方安装包，不下载、创建前缀或改入口。
- `install --uu-installer /绝对路径/官方UU安装包.exe` 校验材料后准备缺失的已固定依赖，安装运行器并初始化私有前缀；官方 UU 的安装与登录仍在其自己的界面完成。
- 下载材料由发行包随附 `downloads.json` 的 HTTPS URL、SHA-256 和体积上限约束。已经存在的用户配置和不匹配文件保留；中断下载不会变成可执行依赖。
- 安装仅写用户级自己的缓存、依赖、运行器、配置、辅助程序及桌面条目；不调用 sudo、不改变系统安全策略或宿主机路由。
- `status` 查询底层状态；`restore` 仅恢复本工具接入的桌面入口，不删除前缀、客户端或登录数据。

本目录的回归测试均使用临时 HOME/XDG、合成依赖和模拟进程；实际运行器、UU 初始化与网络验收另按发行测试记录执行。

## 首次使用

从完整安装包根目录先执行 `cd src`；本节以下 `setup-tool/setup.py` 命令均以该 `src` 目录为当前目录。根目录README的 `src/setup-tool/setup.py` 命令可直接从包根目录执行。

完整安装包保留同级 `setup-tool/`、`native-ux/` 和 `pairing-tool/`，请完整解压。先按发行安装说明准备系统工具，安装原生 Linux Steam 并启动一次完成更新，然后从 Steam 菜单正常退出。当前不支持 Flatpak/Snap Steam。运行以下命令的用户应为平时登录图形桌面的普通用户，不要使用 sudo。

```sh
python3 -B setup-tool/setup.py check
python3 -B setup-tool/setup.py install --uu-installer "/绝对路径/官方UU安装包.exe"
```

`check` 中的 `host_ready` 表示本机前置条件，不表示完整集成已经安装或游戏已经加速。缺少的固定 wrapper/pasta 列为安装时自动补齐材料，不作为主机缺陷；用户显式指定但无效的依赖路径仍会阻止安装。GUI 库、`zh_CN.UTF-8`、图形会话、TUN 与系统工具的问题须先按实际报错处理。安装器不会自动改系统安全策略或执行包管理器命令。

首次运行会从本版 GitHub 附件下载并校验固定运行器、wrapper 和 pasta，文件名、来源、SHA-256 与体积上限由 `downloads.json` 约束。GitHub 官方 HTTPS 附件服务重定向受到限定。下载中断、哈希不符或超出体积限制时不发布可执行文件；已存在的不匹配缓存和用户改动保留并报错。wrapper 的 Steam Linux Runtime 首次下载仍可能需要额外时间及空间。

按照出现的官方 UU 安装界面完成安装；账号与登录只在客户端自己的界面操作。客户端及 Windows 注册表确认存在之后，安装器才发布 Python 集成和接入普通 Steam/UU 图标，并安装“Felix 配对”菜单及 SVG。全新 UU 入口从本机已安装的官方 `uu_launcher.exe` 静态读取品牌图标，不使用安装器带纸箱的图标；已有 UU 条目继续保留原 Icon。日常使用两个原图标；游戏、节点和路由模式继续在 UU 中选择。配对工具可以一次采用已经建立的连接，无需重复拖拽。

## 本地材料与重复运行

已经下载发行附件时，可将它们放在安装器的 `assets/`、安装器目录、相邻上级目录或用户 Downloads 目录，由同一固定哈希复用；也可以显式指定本地路径：

```sh
python3 -B setup-tool/setup.py install --offline \
  --runner-archive "/材料/felix-proton-uu-test-0.1.0-test.1.tar.zst" \
  --wrapper "/材料/shorin-proton-wrapper" \
  --pasta "/材料/pasta" \
  --uu-installer "/材料/官方UU安装包.exe"
```

显式指定的 wrapper/pasta 必须已经可执行且满足底层功能检查，pasta 的文件名须为 `pasta`。通过发行清单自动安装的依赖存放在当前用户自己的 `felix-proton-setup/dependencies-v1/` 哈希版本目录，不更改用户 PATH 或覆盖系统工具。`--steam-root`、`--steam` 可指定原生 Steam 的根目录及真实启动器；不能指回本项目启动层。

`--offline` 只禁止本安装器的材料下载；wrapper 自己的 Steam Linux Runtime 尚未缓存时仍需要下载，它不是完整断网安装的承诺。已有正确配置时重复运行复用原依赖、前缀和客户端，不擅自迁移；存在外部变更时底层校验会拒绝覆盖。新的安装选项经 `native-ux/enable.py` 转交原有 `setup_config.ensure_config()`，固定归档与内部四份组件指纹校验保持。`enable.py` 仅允许精确匹配的历史辅助程序升级，不替换用户修改。

自动提供的 pasta 二进制需要 glibc 2.38+，不满足时请使用经功能检查的兼容版本并以 `--pasta` 指定，或采用符合发行依赖要求的系统。有效的已有或显式 pasta 不会因自动附件的 glibc 限制被误拒绝。`check` 会只读验证本版本已有配置与固定运行器身份，再复用其私有依赖路径，不把未加入 PATH 的已安装依赖误报为缺失。

品牌图标代码 `icons.py` 只解析 PE 的 RT_GROUP_ICON/RT_ICON，构成标准 ICO；随后在受内存、CPU、输出体积和超时限制的独立系统 Python 进程中用 GdkPixbuf 解码 PNG，不执行客户端代码。PNG 和来源/哈希记录位于用户自己的 `felix-proton-setup/icons-v1/`。图标提取发生在 UU 安装就绪之后、桌面备份事务之前；失败不会把普通入口切到缺图标状态。厂商品牌资源只在本机生成，不随本项目发行包再分发。

## 状态与回退

```sh
python3 -B setup-tool/setup.py status
python3 -B setup-tool/setup.py restore
```

恢复前先在 UU 正常停止加速，并正常退出应用；若已用配对工具登记连接，先在工具中按说明移除管理记录或解除自己的配对。`restore` 只依据现有底层备份恢复桌面入口，不清除前缀、账号状态、运行器、已下载材料或配对恢复账本。若辅助组件或桌面入口被外部编辑，冲突文件会保留，不能靠删除账本强行重试。安装器不结束任何真实客户端，也不拆除活动网络。

## 本目录测试

```sh
cd setup-tool
python3 -B -m unittest -q
```

当前 26 项隔离回归包含20项安装器与6项合成PE图标测试，覆盖固定下载清单、TLS 来源/重定向、体积和 SHA、部分下载清理、缓存及依赖冲突、离线材料、系统依赖拒绝、显式路径转交、已有配置只读核验/续装、配对菜单失败的部分完成说明，以及PE资源越界/截断、ICO重构、图标发布与外部改动保护。`native-ux/test_enable.py`、`test_desktop.py` 另有显式依赖转交、图标回调时序/失败不接入、新入口图标/已有图标保持与回退回归。它们不能替代真实 Steam Linux Runtime、官方 UU 安装器、共享网络或游戏加速验收。
