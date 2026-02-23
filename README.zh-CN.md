# filesMind（原生 macOS 重构版）

filesMind 当前已切换为纯原生 macOS 技术栈（SwiftUI + Swift Package Manager）。

## 当前技术栈

- 界面层：SwiftUI
- 应用核心：Swift 5.9+（`@Observable`、async/await）
- 数据层：SQLite + GRDB
- 解析/索引/搜索：`native/Packages/Sources` 下的原生模块

本分支已移除历史 Python / Vue / Tauri 代码。

## 仓库结构

- `native/Packages/`：Swift 包工程（主应用 + 模块 + 测试）
- `scripts/test_all.sh`：原生编译测试脚本

## macOS 编译

```bash
cd native/Packages
swift build
```

## 测试

```bash
cd native/Packages
swift test
```

## 调试产物

编译后可执行文件位于：

- `native/Packages/.build/debug/FilesMindApp`

## 说明

- 当前方向面向 Mac App Store 合规的纯原生架构。
- 不再使用本地 HTTP 服务、Python 运行时 Sidecar、Vue 前端构建链路。
