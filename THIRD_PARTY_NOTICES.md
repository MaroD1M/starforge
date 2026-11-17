# 第三方组件与许可

starforge 自身以 **MIT** 发布。发布的 Windows 包内还包含下列第三方组件，各自保留其许可：

| 组件 | 许可 | 用途 | 是否随包分发 |
|---|---|---|---|
| [NMS-Shipwright](https://github.com/S-T-0-7/NMS-Shipwright) | MIT（© 2026 Shikhar Tiwari） | 存档读写、种子生成、几何/涂装、系统生成 | ✅ 以 vendor 形式打包（`nms_save/`、`nms_procgen/`、`data/mapping.json`），许可全文见包内 `THIRD_PARTY_SHIPWRIGHT_LICENSE.txt` |
| [Gagarin_Titov](https://github.com/autoeme/Gagarin_Titov) | 数据文件随游戏分发；字体 SIL OFL 1.1 | 部件目录 `catalog.txt`、缩略图 `icons.bin` | ❌ 不含；由用户本地游戏目录读取 |
| [NMS-Super-Ship-Hunter](https://github.com/beihaixingchen/NMS-Super-Ship-Hunter) | MIT | "模板槽 + 外部写"思路；兼容其两个模板槽的种子常量 | ❌ 不含代码，仅按公开数据做兼容 |
| numpy / Flask / lz4 / hgpaktool / texture2ddecoder / unicorn | 各自许可（BSD/Apache 等） | 运行依赖 | ✅ 由 PyInstaller 打包 |

> 本仓库**不包含**任何游戏原始文件（pak / MBIN / 贴图 / 存档），也不包含上述上游的源码副本；
> vendor 只在 CI 构建时进行，产物带许可说明，源码仓库保持干净。
