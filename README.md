# safecuff-console

安全箍网页版控制台与边缘设备集成仓库。当前仅配置代码管理与设备同步，尚未实现控制台应用。

计划功能：机器人视觉观测、任务状态、安全事件、日志、算法评估与防御介入记录，以及后续安全算法的模块化接口。

## 当前仓库结构

- 本机：`C:\Users\Celestial\WorkSpace\safecuff-console`
- 设备接收仓库：`/home/admin/safecuff-console.git`（裸仓库）
- 设备运行目录：`/home/admin/safecuff-console-dev`（普通克隆）
- 本机分支：`main`
- 本机远程：`edge = ai-edge:/home/admin/safecuff-console.git`
- 设备测试分支：`dev`

本机通过现有SSH别名`ai-edge`推送，沿用其跳板配置。设备运行目录从设备本地裸仓库更新，不依赖设备访问GitHub。

本机此仓库已单独配置使用Windows OpenSSH，解决Git自带SSH在当前PowerShell/ProxyJump环境中调用`exec ssh`失败的问题；没有修改全局Git或SSH配置。另一台Windows开发电脑若遇到相同问题，可在其仓库内执行：

```powershell
git config --local core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe
```

## 日常同步

在本机仓库中修改并提交所需文件，然后执行：

```powershell
git add <需要提交的文件>
git commit -m "Describe the change"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Sync-Edge.ps1
```

脚本要求工作区干净，将当前提交推送到设备`dev`分支，再以`--ff-only`更新设备运行目录，并核对两端提交ID。它不会安装依赖、启动服务或重启机器人程序。如果失败，不会强制覆盖设备上的修改。

也可以手动执行：

```powershell
git push edge HEAD:refs/heads/dev
ssh ai-edge 'git -C /home/admin/safecuff-console-dev pull --ff-only'
```

`git push`本身只更新接收仓库，不会更新运行目录。未提交或被忽略的文件不会同步。请保持设备运行目录不作直接修改；需要设备端调试时，先协调并保存修改，再恢复正常同步。

默认同步同一条连续开发历史。如果本机切换到另一条分支导致非快进推送被拒绝，应先决定分支/部署目录安排，不要默认强制推送。

## GitHub协作与另一台设备

GitHub协作仓库尚未创建或关联。建立后，在本机增加`origin`并按需推送`main`：

```powershell
git remote add origin <GitHub仓库URL>
git push -u origin main
```

每位开发者在自己的设备上采用相同结构，并在自己电脑配置`edge`远程。SSH密钥、连接地址和Git远程配置不随源码提交。

`Sync-Edge.ps1`从`edge`的SSH URL推导主机和运行目录；URL形式需为`SSH别名:/绝对路径/仓库名.git`，运行目录使用同路径下的`仓库名-dev`。也可通过`-Remote`和`-Branch`选择其他远程或测试分支；现有运行目录的分支必须匹配。

## 文件边界

源码、接口定义、依赖清单和部署脚本入Git。设备配置、密钥、虚拟环境、依赖目录、模型权重、日志与录像单独管理；相应目录已经写入`.gitignore`。设备侧Python/原生依赖应在ARM64环境安装，不复制Windows环境。
