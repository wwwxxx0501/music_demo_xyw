# AudioLab — 音频导入解析与平台内曲库搜索

> Electron + React + TypeScript 桌面端音频曲库管理 Demo

![Electron](https://img.shields.io/badge/Electron-28-47848F?logo=electron&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.3-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-06B6D4?logo=tailwindcss&logoColor=white)

---

## 功能概览

| 功能 | 说明 |
|------|------|
| 🎵 **本地音频导入** | 通过系统文件对话框导入 MP3 / AAC / M4A / WAV |
| 📊 **波形可视化** | Canvas 自绘波形条，主进程计算 peaks，支持点击跳转 |
| ▶️ **音频播放** | 播放/暂停、快进/快退 5 秒、音量调节、静音 |
| 🔍 **曲库搜索** | 支持按歌曲名、艺术家关键字搜索 |
| 🌐 **平台曲库** | Mock 平台曲库数据展示，支持加入我的曲库 |
| 📈 **BPM / Beat 分析** | Mock 分析占位（附带 Cue Points 标记），后续可接入 essentia.js 等 |
| 🌙 **深色主题** | DAW 风格暗色 UI |

---

## 技术架构

```
┌──────────────────────────────────────────────────┐
│                  Electron Main                    │
│  ┌────────────────┐  ┌─────────────────────────┐ │
│  │  File Dialog    │  │  Local HTTP Audio Server │ │
│  │  IPC Handlers   │  │  (Range Request 支持)    │ │
│  │  Peaks 计算     │  │  Security: allowedPaths  │ │
│  └────────────────┘  └─────────────────────────┘ │
├──────────────────────────────────────────────────┤
│              contextBridge (Preload)              │
├──────────────────────────────────────────────────┤
│                  Renderer (React)                 │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────┐ │
│  │ Sidebar   │ │ SongList │ │ SongDetail        │ │
│  │           │ │          │ │ ├ WaveformPlayer   │ │
│  │           │ │          │ │ └ AnalysisPanel    │ │
│  └──────────┘ └──────────┘ └───────────────────┘ │
│              Zustand Store                        │
└──────────────────────────────────────────────────┘
```

---

## 项目结构

```
audio-library-demo/
├── electron/
│   ├── main.ts              # 主进程：窗口、IPC、HTTP 音频服务、波形计算
│   └── preload.ts           # 预加载脚本：contextBridge API
├── src/
│   ├── components/
│   │   ├── Sidebar.tsx       # 左侧导航 + 导入按钮
│   │   ├── SongList.tsx      # 歌曲列表 + 搜索过滤
│   │   ├── SongDetail.tsx    # 歌曲详情卡片
│   │   ├── WaveformPlayer.tsx# Canvas 波形 + Audio 播放器
│   │   ├── AnalysisPanel.tsx # BPM / Beat / Cue 分析面板
│   │   ├── SearchBar.tsx     # 搜索输入框
│   │   └── ErrorBoundary.tsx # 错误边界
│   ├── store/
│   │   └── useMusicStore.ts  # Zustand 状态管理
│   ├── mock/
│   │   └── platformSongs.ts  # 平台曲库 Mock 数据
│   ├── types/
│   │   └── index.ts          # TypeScript 类型定义
│   ├── utils/
│   │   └── format.ts         # 格式化工具函数
│   ├── styles/
│   │   └── global.css        # 全局样式 + Tailwind
│   ├── App.tsx               # 根组件（三栏布局）
│   ├── main.tsx              # React 入口
│   └── vite-env.d.ts         # 类型声明
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── tailwind.config.js
├── postcss.config.js
└── README.md
```

---

## 快速开始

### 环境要求

- **Node.js** ≥ 18
- **npm** ≥ 9

### 安装与运行

```bash
# 克隆仓库
git clone <repo-url>
cd audio-library-demo

# 安装依赖
npm install

# 国内用户如遇 Electron 下载慢，设置镜像：
# set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/   (Windows CMD)
# $env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/" (PowerShell)

# 启动开发模式
npm run dev

# 生产构建
npm run build
```

---

## 核心数据结构

```typescript
interface Song {
  id: string
  title: string
  artist: string
  duration: number           // 秒
  format: string             // mp3 / aac / m4a / wav
  fileSize: number           // 字节
  sourceType: 'local_file' | 'internal_catalog'
  sourcePath: string         // 本地路径，平台歌曲为空
  importStatus: 'importing' | 'ready' | 'error'
  analysisStatus: 'none' | 'analyzing' | 'completed' | 'error'
  bpm: number | null
  beatPoints: number[]       // 节拍时间戳（秒）
  cuePoints: CuePoint[]      // 标记点
  createdAt: number
}
```

---

## Electron IPC 接口

| 通道 | 方向 | 说明 |
|------|------|------|
| `dialog:openAudioFiles` | Renderer → Main | 打开文件选择对话框，返回文件信息数组 |
| `audio:getServerPort` | Renderer → Main | 获取本地音频 HTTP 服务端口号 |
| `audio:getPeaks` | Renderer → Main | 从文件计算波形峰值数据（200 个采样点） |

---

## 安全设计

- **contextIsolation**: 渲染进程与 Node.js 隔离
- **allowedPaths**: 只有用户通过对话框选择的文件才能被 HTTP 服务提供
- **CSP**: Content-Security-Policy 限制资源加载源
- **本地回环**: 音频 HTTP 服务仅监听 `127.0.0.1`

---

## 扩展方向

- [ ] 接入真实 BPM 检测算法（essentia.js / aubio WASM）
- [ ] 音频转码（FFmpeg WASM）
- [ ] 拖拽导入
- [ ] 歌曲封面提取（ID3 标签解析）
- [ ] 波形缩放 & 细粒度编辑
- [ ] 导出分析报告

---

## 许可

MIT
