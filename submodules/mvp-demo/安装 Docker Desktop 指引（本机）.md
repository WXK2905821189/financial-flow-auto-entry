<title>本机安装 Docker Desktop 指引（Windows 11）</title>

# 本机安装 Docker Desktop（Windows 11）

> 目的：为「一期 MVP 演示栈」提供运行环境。你的本机当前未检测到 Docker，按本指引装好后即可用 `docker compose up` 一键拉起演示。
> 关联：见 `mvp-demo/README.md`。

---

## 一、安装前检查

按 `Win + R` → 输入 `winver` 确认系统版本为 **Windows 10/11 (64 位)**，并确认 BIOS 虚拟化已开启：

- 任务管理器 → 性能 → CPU → 右下角「虚拟化」应为 **已启用**。
- 若显示「已禁用」，需进 BIOS 开启 **Intel VT-x / AMD-V**（各主板路径不同，见说明书），改完重启。

---

## 二、安装步骤

1. **下载 Docker Desktop**（约 500MB）
   官方地址：<https://www.docker.com/products/docker-desktop/>
   选择 **Windows** 版本 x86_64。

2. **安装**
   - 双击安装包，按默认选项安装，勾选 **Install required Windows components for WSL 2**（推荐，Linux 容器运行更快）或改用 **Hyper-V**。
   - 安装完成后**重启电脑**（WSL 2 后端通常必须重启）。

3. **启动 Docker Desktop**
   - 开始菜单搜索 **Docker Desktop** 打开；首次会走一次初始化（可能提示下载 WSL2 内核，照做）。
   - 等待状态变为绿色 **Engine running**（托盘鲸鱼图标不闪即可）。
   - **登录**：Docker Desktop 默认会弹出登录（用 Docker Hub 账号）；免费个人账号即可，注册无需付费。

4. **验证安装**
   打开 PowerShell 或终端，执行：
   ```powershell
   docker --version
   docker compose version
   ```
   两条都能输出版本号即安装成功。

---

## 三、常见问题

| 现象 | 处理 |
|-|-|
| `docker` 不是内部或外部命令 | 安装完成后未重启 / 未重开终端；重启后再试 |
| 提示 `WSL 2 未安装` | Settings → Resources → WSL Integration 开启；或 `wsl --install` 后重启 |
| Engine 无法启动 / 一直在 starting | 关闭第三方安全软件；确认虚拟化已开启；或用 Hyper-V 后端重装 |
| 国内拉镜像慢 | 在 Docker Desktop Settings → Docker Engine 写入国内加速源（如镜像加速器），Apply & Restart |

---

## 四、装好后

回到演示栈目录执行一键启动：

```powershell
# 进入演示栈目录
cd "c:\Users\王小棵\Documents\财务流水自动化\财务流水自动入账项目\mvp-demo"

# 一键构建并拉起四个服务 + MySQL
docker compose up --build -d

# 浏览器打开演示入口
start http://localhost:8080
```

完整演示步骤见 `mvp-demo/README.md`。