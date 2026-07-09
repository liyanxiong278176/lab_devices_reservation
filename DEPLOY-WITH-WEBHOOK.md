# GitHub Webhook 自动部署指南

> 目标:把 `lab_devices_reservation` 部署到 **腾讯云 OpenCloudOS 9.6 + 宝塔面板** 服务器上,实现 `git push origin main` 后自动 `git pull` → `docker compose -f docker-compose.prod.yml up -d --build`。
>
> 服务器:腾讯云 CVM,系统 OpenCloudOS 9.6 (RHEL 9 系列,`dnf` / `systemd` / `firewalld`),`root` 账号直连,装了**宝塔面板**(默认 `lighthouse` 用户、`/www/wwwroot` 网站根)。
>
> 适用项目:Spring Boot 3.2.5 (Java 17) + Vite/React + docker-compose(本仓库现状)。**编译完全在 Docker 里做**(后端 `maven:3.9-eclipse-temurin-17` → `eclipse-temurin:17-jre`;前端 `node:20-alpine` → `nginx:alpine`),宿主机**不需要**装 JDK / Maven / Node。
>
> 项目路径: `/www/wwwroot/lab_devices_reservation`
> 生产 compose: `docker-compose.prod.yml`(含 mysql/redis/app/frontend,顶级 `name: labprod`)
> 注意:仓库根的 `docker-compose.yml` **是 dev 用的**(只有 mysql+redis),**不要**让 deploy 脚本碰它。

---

## 目录

- [0. 流程总览](#0-流程总览)
- [1. 方案对比](#1-方案对比)
- [2. 方案一:Webhook(主推)](#2-方案一webhook主推)
  - [Phase 1 — 安装基础环境](#phase-1--安装基础环境)
  - [Phase 2 — 确认 webhook 工具就位](#phase-2--确认-webhook-工具就位)
  - [Phase 3 — 创建部署目录](#phase-3--创建部署目录)
  - [Phase 3.5 — 写 .env 生产环境变量](#phase-35--写-env-生产环境变量)
  - [Phase 4 — 写部署脚本](#phase-4--写部署脚本)
  - [Phase 5 — 写 webhook 配置](#phase-5--写-webhook-配置)
  - [Phase 6 — 注册 systemd 服务](#phase-6--注册-systemd-服务)
  - [Phase 7 — 配置 git 凭证](#phase-7--配置-git-凭证)
  - [Phase 8 — 防火墙与腾讯云安全组](#phase-8--防火墙与腾讯云安全组)
  - [Phase 9 — GitHub 仓库侧配置](#phase-9--github-仓库侧配置)
  - [Phase 10 — 验证一次完整链路](#phase-10--验证一次完整链路)
- [3. 方案二:GitHub Actions + 自托管 Runner](#3-方案二github-actions--自托管-runner)
- [4. 常见问题](#4-常见问题)
  - [Q1:GitHub 那边 webhook 显示红色三角(投递失败)](#q1github-那边-webhook-显示红色三角投递失败)
  - [Q2:deploy.sh 跑成功但容器没起来](#q2deploysh-跑成功但容器没起来)
  - [Q3:git pull 报 "Permission denied (publickey)"](#q3git-pull-报-permission-denied-publickey)
  - [Q4:`flock` 锁住了,旧部署卡死](#q4flock-锁住了旧部署卡死)
  - [Q5:想让 push 不只是 main 触发](#q5想让-push-不只是-main-触发)
  - [Q6:`mv` 装 webhook 时报 "cannot overwrite directory"](#q6mv-装-webhook-时报-cannot-overwrite-directory)
  - [Q7:deploy.sh 跑 `docker compose` 报 exit status 125](#q7deploysh-跑-docker-compose-报-exit-status-125body-显示-docker-帮助文本)
- [5. 卸载 / 清理](#5-卸载--清理)

---

## 0. 流程总览

```
开发者                     GitHub                    腾讯云 OpenCloudOS 9.6
  │                          │                              │
  │  git push origin main    │                              │
  ├─────────────────────────▶│                              │
  │                          │  POST /hooks/deploy-xxx      │
  │                          │  + X-Hub-Signature-256       │
  │                          ├─────────────────────────────▶│
  │                          │                              │ 1. webhook 进程收到
  │                          │                              │ 2. 校验 HMAC 签名
  │                          │                              │ 3. 校验 ref=main
  │                          │                              │ 4. 执行 deploy.sh
  │                          │                              │    ├─ git pull
  │                          │                              │    └─ docker compose up --build
  │                          │◀──── 200 OK + 日志 ──────────┤
```

**关键安全点**:HMAC 签名(`X-Hub-Signature-256`)是 GitHub 用来证明"这次 POST 真的来自 GitHub"的机制,不校验任何人都能 POST 触发你的部署。

**为什么宿主不需要 JDK/Maven**:`Dockerfile` 第一行就是 `FROM maven:3.9-eclipse-temurin-17 AS builder`,`mvn package` 在镜像里跑完才出 jar;第二阶段 `eclipse-temurin:17-jre` 只拷 jar 跑,运行时也只需要 JRE。所以宿主机有 `docker` 就行。

---

## 1. 方案对比

| 维度 | 方案一 Webhook | 方案二 Actions + Runner |
|---|---|---|
| 服务器常驻进程 | 1 个轻量 webhook | 1 个 Actions Runner(更重) |
| 编排能力 | 弱(就一个 shell 脚本) | 强(可分 job、matrix、cache) |
| 触发条件灵活性 | 弱(只接 push) | 强(PR、定时、手动) |
| 日志/可观测 | 自己看 `journalctl` | GitHub UI 一目了然 |
| 调试难度 | 低(改脚本立刻生效) | 中(要走一次 workflow) |
| 适合 | 单项目、单环境 | 多项目、多环境、CI 一体化 |

**建议先方案一**,等以后有第二台机器或多个分支环境再升级到方案二。

---

## 2. 方案一:Webhook(主推)

> 前置:你已有一台腾讯云 CVM,系统 OpenCloudOS 9.6,能用 `ssh root@<公网IP>` 连上。
> 假定仓库代码已 clone 到 `/www/wwwroot/lab_devices_reservation`(`git clone ...`)。

### Phase 1 — 安装基础环境

```bash
sudo dnf install -y git openssh-clients
```
> 🎯 装两个包就够了:
> - `git`:拉取远程代码
> - `openssh-clients`:`ssh-keygen` 用,生成 deploy key

```bash
git --version
docker --version
docker compose version
```
> 🎯 三个 `-version` 验安装,任一报错就别往下走。预期 Git 2.x、Docker 20.x+、`docker compose version` 走 v2 插件(输出 `Docker Compose version v2.x.x`)。

**注意**:OpenCloudOS 9.6 默认不带 `docker`,要自己装一遍。两种方式任选:

**A. 用官方 docker-ce 仓库**(强烈推荐):
```bash
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```
> 🎯 这一组**带 `docker-compose-plugin`**= 装出来是 v2 插件(命令是 `docker compose` 空格分隔),deploy.sh 直接能用。

**B. TencentOS Server / OpenCloudOS 自带源**(离线友好):
```bash
sudo dnf install -y docker docker-compose
sudo systemctl enable --now docker
```
> ⚠️ **这条命令装出来只有 v1 独立版 `docker-compose`(连字符)**,**没有 v2 插件**。如果你不想换 docker 源,可以继续用,但 deploy.sh 里所有 `docker compose` 必须改成 `docker-compose`(一行 sed),详见 **Q7**。不想折腾就老老实实走方案 A。

**装完再 double-check 一下**(两种方式都要验):
```bash
which docker docker-compose 2>&1
docker compose version 2>&1 | head -3
docker-compose --version 2>&1 | head -3
```
> 🎯 期望两种**至少**有一种有结果:
> - **A 走通了**:`docker compose version` 输出 v2.x;`docker-compose` 没装是正常的(`which` 不出来)
> - **B 走通了**:`docker-compose --version` 输出 v1.x;`docker compose version` 报"unknown command"
>
> 如果**两个都装了也没事**,v2 优先级更高。
>
> 如果**两个都没装**(`which docker-compose` 空 + `docker compose version` 报错)→ 装 docker 没装全,回去重装,见 Q7。

### Phase 2 — 确认 webhook 工具就位

**当前现状**:已经手动把 webhook 二进制放到 `/usr/bin/webhook`,这一 Phase 只做确认。

```bash
which webhook
webhook -version
```
> 🎯 `which` 看路径(应输出 `/usr/bin/webhook`),`-version` 验能跑(应输出 `webhook version 2.8.2`)。
>
> 如果之前 `mv` 报 "cannot overwrite directory" 见 **Q6** 修法。

### Phase 3 — 创建部署根目录

> **极简版**:一个目录搞定所有 deploy 相关的东西 —— `hooks.json` / `deploy.sh` / `deploy.log` / `deploy.lock` 全在 `/root/webhook-deploy/` 下。`chmod 700` 让 root 之外的人进都进不来,等于自带 secret 保护。

```bash
sudo mkdir -p /root/webhook-deploy
sudo chmod 700 /root/webhook-deploy
```
> 🎯 一个目录 = 4 类文件,省去分别建 4 个 FHS 标准目录(`/etc/webhook` / `/opt/deploy/...` / `/var/log/deploy` / `/var/lock`)的麻烦。`chmod 700` 已经把 secret 隔离做了,后续 `hooks.json` 不用再单独 `chmod 600`。

```bash
ls -ld /root/webhook-deploy
```
> 🎯 验证,应看到 `drwx------ root root ... /root/webhook-deploy`(`700` + 属主 root)。

```bash
sudo chown -R root:root /www/wwwroot/lab_devices_reservation
```
> 🎯 代码目录属主改为 `root`(让 `root` 跑的 deploy 脚本能 `git pull` 写)。

```bash
ls -la /www/wwwroot/
```
> 🎯 验证代码目录在,属主是 root。

### Phase 3.5 — 写 .env 生产环境变量

> `docker-compose.prod.yml` 用了 `${DB_PASSWORD:-default}` / `${JWT_SECRET:-default}` 的兜底写法:**不写 .env 也能起来**,但**默认密码太弱**。生产环境必须用自己的。

```bash
openssl rand -hex 32
```
> 🎯 生成一个 32 字节的随机十六进制串,64 字符长,粘到下面 `JWT_SECRET=` 后面。

```bash
openssl rand -base64 24
```
> 🎯 再生成一个数据库密码,粘到 `DB_PASSWORD=` 后面(`base64` 出来的字符容易有 `+` `/` `=`,**docker compose 会接受,不需要 URL 编码**)。

```bash
sudo vim /www/wwwroot/lab_devices_reservation/.env
```
> 🎯 写 `.env` 文件(docker compose 自动读),**注意:文件名就是 `.env`,无后缀**。

写入:

```bash
# 生产环境强密码(自己生成替换)
DB_PASSWORD=<上面 base64 那个>
JWT_SECRET=<上面 hex 那个>

# 端口(项目里基本用不到 80/8080 对外暴露,可省略)
# FRONTEND_PORT=80
```

```bash
sudo chmod 600 /www/wwwroot/lab_devices_reservation/.env
```
> 🎯 `.env` 里有密码,设成只有 root 能读写。

```bash
cd /www/wwwroot/lab_devices_reservation && docker compose -f docker-compose.prod.yml config | grep -E "PASSWORD|SECRET"
```
> 🎯 跑 `docker compose config` 解析最终配置,grep 出密码相关字段确认值不是 `LabSecurePwd2026` 那个默认,说明 `.env` 被正确读到了。

### Phase 4 — 写部署脚本

```bash
sudo vim /root/webhook-deploy/deploy.sh
```
> 🎯 用 vim 打开脚本文件(`vim` 没有就用 `vi` 或 `nano`)。

写入以下内容:

```bash
#!/bin/bash
set -euo pipefail

DEPLOY_DIR=/root/webhook-deploy
APP_DIR=/www/wwwroot/lab_devices_reservation
COMPOSE_FILE=docker-compose.prod.yml
LOG_FILE="$DEPLOY_DIR/deploy.log"
LOCK_FILE="$DEPLOY_DIR/deploy.lock"

# 并发锁:同一时刻只允许一次部署
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "[$(date)] another deploy in progress, skip"; exit 1; }

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"; }

log "=== deploy start ==="
cd "$APP_DIR"

git fetch --all
git reset --hard origin/main
log "git pull done, HEAD=$(git rev-parse --short HEAD)"

# 编译和启动全在容器里做(后端 mvn + 前端 pnpm build,都在 Dockerfile 多阶段里跑)
# 用 -f 显式指定 prod compose —— 仓库根的 docker-compose.yml 是 dev 用的(只 mysql+redis),不能碰
docker compose -f "$COMPOSE_FILE" down
docker compose -f "$COMPOSE_FILE" up -d --build
log "docker compose up done"

# 健康检查:走 frontend 80 端口 → 反代到 app:8080/api/actuator/health
# 注意 Spring context-path=/api,所以是 /api/actuator/health 不是 /actuator/health
sleep 15
if curl -fs http://127.0.0.1/api/actuator/health 2>/dev/null | grep -q '"status":"UP"'; then
    log "health check OK"
else
    log "WARN: health check failed, see docker logs"
fi

log "=== deploy finished ==="
```

逐行解释:

| 行 | 作用 |
|---|---|
| `#!/bin/bash` | shebang,告诉系统用 bash 执行 |
| `set -euo pipefail` | `-e` 遇错就退出,`-u` 用未定义变量就报错,`-o pipefail` 管道里任一环节失败整体失败 |
| `DEPLOY_DIR` | 部署根目录,所有 deploy 文件(脚本/log/lock)都在这里 |
| `APP_DIR` | 项目代码目录,宝塔默认是 `/www/wwwroot/<项目名>` |
| `COMPOSE_FILE` | **用 prod 的 compose**;仓库根的 `docker-compose.yml` 是 dev 用的 |
| `LOG_FILE` / `LOCK_FILE` | 全在 `$DEPLOY_DIR` 下,不分散 |
| `exec 9>"$LOCK_FILE"` | 打开 fd 9 指向锁文件,后续 `flock` 用 |
| `flock -n 9 \|\| { ... exit 1; }` | `-n` 非阻塞拿锁;拿不到说明上一次还在跑,直接退出 |
| `log()` | 自定义日志函数,同时打到终端和文件 |
| `git fetch --all` | 拉取所有远程分支最新引用,**不合并** |
| `git reset --hard origin/main` | 强复位到 `origin/main`,抛弃本地可能有的脏改动 |
| `docker compose -f "$COMPOSE_FILE" down` | 先停掉旧容器释放端口 |
| `docker compose -f "$COMPOSE_FILE" up -d --build` | `--build` 重新构建(`mvn package` + `pnpm build` 在容器里跑),`-d` 后台;镜像变了 Compose 自动重建容器 |
| `sleep 15` | 容器起来后给 15 秒(后端 + Flyway migration + 前端 nginx 都启动) |
| `curl ... /api/actuator/health` | **走前端 80 端口反代**到后端;context-path 是 `/api`,不要漏前缀 |

```bash
sudo chmod +x /root/webhook-deploy/deploy.sh
```
> 🎯 给脚本加可执行位。

### Phase 5 — 写 webhook 配置

```bash
SECRET=$(openssl rand -hex 32)
echo "$SECRET"
```
> 🎯 生成一个 64 字符(32 字节十六进制)的随机串,这就是 webhook 的"密码"。**记下来**,GitHub 那边要配一样的。

```bash
sudo vim /root/webhook-deploy/hooks.json
```
> 🎯 打开 webhook 配置文件。

写入:

```json
[
  {
    "id": "deploy-lab-devices",
    "execute-command": "/root/webhook-deploy/deploy.sh",
    "command-working-directory": "/www/wwwroot/lab_devices_reservation",
    "include-command-output-in-response": true,
    "response-message": "deploy triggered",
    "trigger-rule": {
      "and": [
        {
          "match": {
            "type": "payload-hmac-sha256",
            "secret": "把上面 SECRET 粘贴进来",
            "parameter": {
              "source": "header",
              "name": "X-Hub-Signature-256"
            }
          }
        },
        {
          "match": {
            "type": "value",
            "value": "refs/heads/main",
            "parameter": { "source": "payload", "name": "ref" }
          }
        }
      ]
    }
  }
]
```

字段解释:

| 字段 | 含义 |
|---|---|
| `id` | webhook 路由 ID,URL 里就是 `/hooks/<id>` |
| `execute-command` | 触发时执行的命令(你的 deploy.sh) |
| `command-working-directory` | 执行命令的工作目录 |
| `include-command-output-in-response` | 把脚本的 stdout 写进 webhook 响应(便于 GitHub 那边的 redelivery 看) |
| `response-message` | 触发成功返回给 GitHub 的固定消息 |
| `trigger-rule.and` | 两条规则**都满足**才触发 |
| ├─ `payload-hmac-sha256` | 校验 GitHub 在 header 里带的 `X-Hub-Signature-256` 与 `secret` 计算的 HMAC 一致 |
| └─ `value == refs/heads/main` | 只对 `main` 分支的 push 生效,其他分支不触发 |

```bash
# hooks.json 不需要单独 chmod 600 —— 上层目录 /root/webhook-deploy 已经是 700,root 之外的人根本进不来
```

### Phase 6 — 注册 systemd 服务

```bash
sudo vim /etc/systemd/system/webhook.service
```
> 🎯 新建 systemd unit 文件,这样 webhook 能开机自启、挂了自动拉起。

写入:

```ini
[Unit]
Description=GitHub Webhook Listener
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/www/wwwroot/lab_devices_reservation
ExecStart=/usr/bin/webhook -hooks /root/webhook-deploy/hooks.json -verbose -port 9000
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

`ExecStart` 拆解:

| 参数 | 作用 |
|---|---|
| `-hooks /root/webhook-deploy/hooks.json` | 指定配置文件 |
| `-verbose` | 输出详细日志到 stdout(被 journalctl 接管) |
| `-port 9000` | 监听 9000 端口(可改) |

> 📌 什么时候加 `-secure`?这个 flag 在 adnanh/webhook 里**是启用 HTTPS / TLS** 的开关(需要 `cert.pem` + `key.pem` 在工作目录,或用 `-cert` / `-key` 指定路径)。现在先用 HTTP 跑通,等真的要在公网加密传输(比如挂了腾讯云免费证书)再开。

```bash
sudo systemctl daemon-reload
```
> 🎯 重新读 systemd 配置,让新建的 `webhook.service` 生效。

```bash
sudo systemctl enable webhook
```
> 🎯 开机自启(创建软链到 multi-user.target.wants)。

```bash
sudo systemctl start webhook
```
> 🎯 立即启动。

```bash
sudo systemctl status webhook
```
> 🎯 看状态,预期 `active (running)`。如果 `failed`,用下面这行查日志。

```bash
sudo journalctl -u webhook -f
```
> 🎯 实时跟踪 webhook 服务的日志,`Ctrl+C` 退出。**这是排错第一站**。

### Phase 7 — 配置 git 凭证

> 以 `root` 跑服务,`~` 就是 `/root`。

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/known_hosts
```
> 🎯 建 `.ssh` 目录,权限 700(只许自己读写),并建好 `known_hosts` 占位文件。

```bash
ssh-keygen -t ed25519 -C "root@tencent-cvm" -f /root/.ssh/id_ed25519 -N ""
```
> 🎯 用 ed25519 算法生成密钥对,`-N ""` 留空密码(让 deploy 脚本非交互执行)。公钥路径 `.pub` 那份。

```bash
cat /root/.ssh/id_ed25519.pub
```
> 🎯 把公钥打印出来,完整复制。**下一步要粘到 GitHub 仓库**。

去 GitHub 仓库页面:
1. `Settings` → `Deploy keys` → `Add deploy key`
2. Title: `tencent-cvm-webhook`
3. Key: 粘贴上面公钥
4. **Allow write access**:不勾(只读就够)
5. `Add key`

```bash
cat > ~/.ssh/config <<EOF
Host github.com
  StrictHostKeyChecking accept-new
EOF
chmod 600 ~/.ssh/config
```
> 🎯 写 ssh config,把 GitHub 的"首次连接确认"从交互改成自动接受(否则 webhook 第一次拉取会卡住问 yes/no)。

```bash
ssh -T git@github.com
```
> 🎯 测试连通,预期输出 `Hi <user>/<repo>! You've been granted access.` 然后立刻断开。这是正常的 ssh 测试机制。

### Phase 8 — 防火墙与腾讯云安全组

**8.0 端口清点**

| 端口 | 用途 | 暴露给 |
|---|---|---|
| 9000 | webhook 监听器 | 仅 GitHub(可收窄到 [GitHub 公布的 IP 段](https://api.github.com/meta) `hooks`) |
| 80 | 前端 nginx(用户访问入口) | 公网(`0.0.0.0/0`) |
| 3306 / 6379 / 8080 | mysql / redis / app | **不暴露** —— `docker-compose.prod.yml` 里没 `ports:` 段,只在 docker 网络内互访 |

**8.1 服务器本地 firewalld**

```bash
sudo firewall-cmd --permanent --add-port=9000/tcp
sudo firewall-cmd --permanent --add-port=80/tcp

# 这两条直接跳过,不报错就行
  sudo firewall-cmd --permanent --add-port=9000/tcp 2>/dev/null || echo "firewalld 跳过(宝塔接管)"
  sudo firewall-cmd --permanent --add-port=80/tcp 2>/dev/null || echo "firewalld 跳过(宝塔接管)"

  只去腾讯云控制台配安全组(Phase 8.2 那一步),webhook 走 9000 + 前端走 80,公网能访问就完事。

```
> 🎯 永久放行 9000(webhook)+ 80(前端)两个端口 TCP。**注意不开放 3306/6379/8080**,mysql/redis/app 都在 docker 内部网络里,不应该从公网能连。

```bash
sudo firewall-cmd --reload
```
> 🎯 让 `--permanent` 改动立即生效(不 reload 只对当前 session 有效)。

```bash
sudo firewall-cmd --list-ports
```
> 🎯 验证,应看到 `9000/tcp 80/tcp`。

**8.2 腾讯云控制台安全组**(最常漏)

> 本地 `firewalld` 放行 ≠ 腾讯云允许流量进来。腾讯云在 CVM 之前还有一层**安全组**。

1. 登录 [腾讯云控制台](https://console.cloud.tencent.com/)
2. `云服务器` → 找到你的 CVM → `安全组` 选项卡
3. 点安全组的 `入站规则` → `添加规则`,**加两条**:

| 字段 | 规则 1(webhook) | 规则 2(前端) |
|---|---|---|
| 类型 | 自定义 | HTTP(80) |
| 协议端口 | TCP:9000 | TCP:80 |
| 源 | `0.0.0.0/0`(可收窄到 GitHub hooks IP) | `0.0.0.0/0` |
| 策略 | 允许 | 允许 |
| 备注 | `webhook-listener` | `frontend-public` |

**8.3 宝塔 nginx 占着 80 怎么办?(高概率遇到)**

> 宝塔默认装好就启动了 nginx,**占用 80 端口**。这时候 `docker compose up -d --build` 跑 frontend 时会报:
> ```
> Error response from daemon: driver failed programming external connectivity on endpoint labprod-frontend-1:
> Error starting userland proxy: listen tcp4 0.0.0.0:80: bind: address already in use
> ```

三选一:

**A. 停宝塔 nginx(简单,推荐只用 webhook 部署的人)**
```bash
# 宝塔后台:软件商店 → nginx → 停止
# 或者命令行
sudo systemctl stop nginx
sudo systemctl disable nginx
```

**B. 改 frontend 端口,让宝塔反代(保留宝塔管理界面)**
改 `docker-compose.prod.yml`:
```yaml
frontend:
  build: ./frontend
  ports: ["8088:80"]   # 改这里
```
然后用宝塔建个站点,反向代理到 `http://127.0.0.1:8088`(`location /api/` 和 `/api/ws` 也得配)。

**C. 完全卸宝塔(彻底不混用)**
宝塔后台 → 右上角设置 → 卸载面板(谨慎,会删所有宝塔管理的站点)。

**8.4 本地自测**

```bash
curl -i http://127.0.0.1:9000/
```
> 🎯 本地回环测试 webhook 在不在听。预期 `404 page not found`(因为没带 `/hooks/...` 路径),看到 4xx 说明**进程在跑**;看到 `Connection refused` 说明**没起来**。

```bash
curl -i http://127.0.0.1/
```
> 🎯 **首次手动跑过 deploy.sh 之后**才有意义。预期 `200 OK` + HTML(Vue SPA 的 index.html)。

```bash
curl -fs http://127.0.0.1/api/actuator/health
```
> 🎯 走前端反代到后端健康检查,**注意 `/api` 前缀**(Spring context-path)。预期 `{"status":"UP"}`。

```bash
curl -i http://<公网IP>:9000/
curl -i http://<公网IP>/

curl -i http://1.12.217.11:9000/hooks/deploy-lab-devices
```
> 🎯 公网 IP 自测,通到这一步才说明安全组也放行。**注意**:公网 IP 在 curl 里要替换成你 CVM 实际绑定的 IP(`ip a` 看不到,得在腾讯云控制台看)。

### Phase 9 — GitHub 仓库侧配置

去仓库页面:`Settings` → `Webhooks` → `Add webhook`

| 字段 | 值 |
|---|---|
| Payload URL | `http://<公网IP>:9000/hooks/deploy-lab-devices` |
| **Content type** | **`application/json`** ⚠️ 一定选这个,别选 `application/x-www-form-urlencoded`(选了的话 `trigger-rule` 拿不到 `ref`,会一直 `parameter node not found: ref`,webhook 返回 200 但不触发部署) |
| Secret | 同 Phase 5 那个 `openssl rand -hex 32` 的值 |
| SSL verification | 暂时 Disable(等上 HTTPS 再 Enable) |
| Which events | `Just the push event` |

点 `Add webhook`,跳转后看到 webhook 列表有一条,旁边红/绿图标:
- 红色三角 = 最近一次推送 webhook 投递失败,点 `Edit` 看响应
- 绿色对勾 = 通了

**测试一次**:
- 点 webhook 行的 `Edit` → 底部 `Recent deliveries` → `Redeliver` 可以重放上一次
- 或者直接 `Redeliver` 旁的 `...` 菜单手动发一个 ping

> ⚠️ **首次添加 webhook,GitHub 会自动发一个 "ping" 事件,响应会是 500 + `Hook rules were not satisfied` —— 这是预期行为,不是 bug。**
>
> 原因:ping payload **没有 `ref` 字段**(`ref` 只在 push 事件里),你的 trigger-rule 要求 `ref == refs/heads/main`,ping 自然不满足。webhook 进程如实返回"规则不满足" → GitHub 显示 500。
>
> **真验证就推一次**:`git commit --allow-empty -m "smoke test" && git push origin main`,再回来看 Recent deliveries,最近一次应该是 200 OK(deploy.sh 跑了)。如果 ping 是 500 但 push 是 200,链路就完全通了。

### Phase 10 — 验证一次完整链路

```bash
sudo /root/webhook-deploy/deploy.sh
```
> 🎯 **手动模拟一次部署**。先手动跑通,排除脚本本身的问题,再走 webhook 触发。失败的话终端会直接看到错误信息。

```bash
git commit --allow-empty -m "chore: trigger webhook smoke test"
git push origin main
```
> 🎯 推一个空 commit 到 main,触发 webhook 链路。

```bash
sudo journalctl -u webhook -f
sudo journalctl -u webhook -n 10 --no-pager


```
> 🎯 A 终端开这个,实时看 webhook 收到的请求和它的输出。

```bash
tail -f /root/webhook-deploy/deploy.log
```
> 🎯 B 终端开这个,看部署脚本的日志(`docker compose build` / `docker compose up` 的输出)。

```bash
docker ps
```
> 🎯 C 终端开这个,看新容器是否起来、状态是不是 `Up`(不是 `Restarting` / `Exited`)。`labprod` 前缀的容器名是 prod 的(`name: labprod`)。

```bash
docker compose -f /www/wwwroot/lab_devices_reservation/docker-compose.prod.yml ps
```
> 🎯 同样效果,直接用 prod compose 视角看。

```bash
curl -fs http://127.0.0.1/api/actuator/health
```
> 🎯 健康检查走前端 80 → 反代到 app:8080/api/actuator/health。预期返回 `{"status":"UP"}`。**注意 `/api` 前缀,漏了会 404**。

```bash
docker logs -f labprod-app-1
```
> 🎯 进 app 容器日志看启动排错。`labprod` 是 compose 顶级 name,`app` 是 service 名,合起来是容器名前缀(`docker ps` 里能确认)。

```bash
docker logs -f labprod-frontend-1
```
> 🎯 前端容器日志,看 nginx 是否正常起来。

如果链路通的标志:
- `journalctl` 里 webhook 返回 `200 OK`
- `/root/webhook-deploy/deploy.log` 末尾有 `=== deploy finished ===`
- `docker ps` 看到 4 个 `labprod-*` 容器全 `Up`(mysql/redis/app/frontend)
- `/api/actuator/health` 返回 `UP`

---

## 3. 方案二:GitHub Actions + 自托管 Runner

> 适合:多项目、多环境、想用 GitHub UI 看日志。
> 缺点:Runner 进程比 webhook 重;Runner 本身需要时不时升级。

### 3.1 仓库侧 workflow 文件

新建 `.github/workflows/deploy.yml`:

```yaml
name: deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: self-hosted        # 关键:用你自己的 Runner
    steps:
      - uses: actions/checkout@v4
        with:
          path: /www/wwwroot/lab_devices_reservation

      - name: deploy
        working-directory: /www/wwwroot/lab_devices_reservation
        run: |
          docker compose -f docker-compose.prod.yml down
          docker compose -f docker-compose.prod.yml up -d --build
```

> 🎯 字段解释:
> - `on.push.branches: [main]`:只在 `main` 分支 push 时触发
> - `runs-on: self-hosted`:**关键**,告诉 GitHub 不要用官方 runner,而是派给绑定到本仓库的 self-hosted runner
> - `actions/checkout@v4` 的 `path:` + 后面的 `working-directory`:都指到宝塔默认的项目路径
> - `docker compose -f docker-compose.prod.yml down/up`:跟方案一脚本里那段一样,**编译在容器里做**

### 3.2 服务器装 Runner

```bash
mkdir -p /opt/actions-runner && cd /opt/actions-runner
```
> 🎯 Runner 装在 `/opt/actions-runner`,跟项目代码分开。

```bash
curl -L -o runner.tar.gz https://github.com/actions/runner/releases/download/v2.319.1/actions-runner-linux-x64-2.319.1.tar.gz
```
> 🎯 下最新 Runner(去 [releases](https://github.com/actions/runner/releases) 看当前版本)。

```bash
tar xzf ./runner.tar.gz
```
> 🎯 解压,会得到 `config.sh` / `run.sh` / `svc.sh` 等。

注册 Runner(去 GitHub 拿 token):
1. 仓库 → `Settings` → `Actions` → `Runners` → `New self-hosted runner`
2. 选 Linux x64,会显示一段带 token 的 `config.sh` 命令
3. 复制下来,大致是:
   ```bash
   ./config.sh --url https://github.com/<user>/lab_devices_reservation --token <TOKEN>
   ```
4. 执行,会问 runner 名字(随便)、标签(留空回车)、工作目录(默认即可)

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```
> 🎯 注册成 systemd 服务,以**当前用户**(root)身份跑。
> - `svc.sh install` 默认给当前用户装
> - 如果想换用户跑,先 `sudo chown -R <user>:<user> /opt/actions-runner` 再装

```bash
sudo systemctl status actions.runner.*
```
> 🎯 验证 Runner 服务在跑(服务名带仓库名后缀)。

### 3.3 验证

`git push origin main` → 仓库 → `Actions` 标签页 → 看 workflow 跑没跑、哪步红了。

---

## 4. 常见问题

### Q1:GitHub 那边 webhook 显示红色三角(投递失败)

```bash
sudo journalctl -u webhook -n 100
```
> 🎯 看最近 100 行 webhook 日志。

常见原因:
- **响应超时**:deploy.sh 跑超过 10 秒 webhook 还没回 200。`include-command-output-in-response: true` 时 webhook 会等脚本跑完才回响应。改:
  ```json
  "include-command-output-in-response": false
  ```
  并在脚本最后一行写 `echo done`,webhook 立刻回 200,真正的构建在后台跑。
- **HMAC 校验失败**(真 secret 不匹配 vs 算法错):
  - 先看日志有没有这一行 `warn: use of deprecated option payload-hash-sha256: use payload-hmac-sha256 instead`。**有的话就是这个 bug 不是 secret 错**:adnanh/webhook 2.8.2 把老名字 `payload-hash-sha256` 重定向成了**不带 secret 的纯 SHA-256**,跟 GitHub 发的 HMAC-SHA256 永远对不上,哪怕 secret 字符串完全一样。**改成 `payload-hmac-sha256` 才走真 HMAC。**
    ```bash
    sudo sed -i 's/"payload-hash-sha256"/"payload-hmac-sha256"/' /root/webhook-deploy/hooks.json
    sudo systemctl restart webhook
    ```
  - 没有 deprecation warning 才考虑真 secret 错位:`secret` 跟 GitHub 那边对不上,或 `hooks.json` 里有不可见字符。用 `xxd /root/webhook-deploy/hooks.json | grep secret` 看二进制。
- **腾讯云安全组没放行 9000**:`firewalld` 和云厂商安全组是两个独立层。

### Q2:deploy.sh 跑成功但容器没起来

```bash
docker compose ps -a
docker compose logs --tail=200
```
> 🎯 看容器状态和最近 200 行日志。

常见原因:
- `docker-compose.yml` 里 `.env` 缺值
- 端口被占(`netstat -tlnp | grep 8080`)
- Dockerfile 构建失败(看 `docker compose build` 的输出,通常是网络/依赖问题)

### Q3:git pull 报 "Permission denied (publickey)"

```bash
ssh -T git@github.com
```
> 🎯 显式测一次 SSH,看具体错。

常见原因:
- Deploy key 没配到仓库
- `~/.ssh/config` 里 `StrictHostKeyChecking` 没改
- 用了 HTTPS 协议而非 SSH(把 origin 改成 `git@github.com:user/repo.git`)

### Q4:`flock` 锁住了,旧部署卡死

```bash
fuser /root/webhook-deploy/deploy.lock
```
> 🎯 看哪个进程占了锁文件,杀掉就行。

或者直接清锁(慎用):
```bash
sudo rm /root/webhook-deploy/deploy.lock
```

### Q5:想让 push 不只是 main 触发

改 `hooks.json` 的 `trigger-rule`:
```json
"match": {
  "type": "value",
  "value": "refs/heads/release/*",
  "parameter": { "source": "payload", "name": "ref" }
}
```
> 🎯 改成 `release/*` 通配所有 `release/xxx` 分支推送触发。

### Q6:`mv` 装 webhook 时报 "cannot overwrite directory"

完整报错:
```
mv: cannot overwrite directory '/usr/local/bin/webhook' with non-directory
```

**原因**:`/usr/local/bin/webhook` 这个路径**已经被一个同名目录占住了**(很可能是之前某次安装残留、空目录,或别的脚本目录),`mv` 文件进去会被拒绝。

**修法** —— 改名让路,不要直接 `rm -rf`:
```bash
ls -la /usr/local/bin/webhook
```
> 🎯 先看清里面是什么:是空目录就直接删;看着像别的程序的东西就改个名留着。

#### 子情形 A:`/usr/local/bin/webhook` 是个文件

就是上一版的 `webhook` 二进制,直接挪开:
```bash
sudo mv /usr/local/bin/webhook /usr/local/bin/webhook.old
sudo mv webhook-linux-amd64/webhook /usr/local/bin/webhook
sudo chmod +x /usr/local/bin/webhook
```

#### 子情形 B:`/usr/local/bin/webhook` 是个目录(更常见)

```
/usr/local/bin/webhook/                  ← 占着路径的目录
/usr/local/bin/webhook/webhook           ← 6MB+ 的二进制就在里头
/usr/local/bin/webhook/webhook-linux-amd64/   ← 残留空目录
```

这种情况意味着**之前的 `mv` 实际上成功了一半** —— 文件被搬进了目录,而不是被拒绝;或者之前有别的程序占了同名目录。这种就不能用"改名 + 再 `mv` 一次"的修法了,要从目录里**抽出**二进制:
```bash
cd /usr/local/bin
sudo mv /usr/local/bin/webhook /usr/local/bin/webhook.dir.bak
sudo mv /usr/local/bin/webhook.dir.bak/webhook /usr/local/bin/webhook
sudo chmod +x /usr/local/bin/webhook
sudo rm -rf /usr/local/bin/webhook.dir.bak
hash -r
```

**还有个相关坑**:`mv` 完之后 `webhook -version` 报 `/usr/bin/webhook: No such file or directory`,不是 `/usr/local/bin/webhook`:
```bash
hash -r
```
> 🎯 `mv` 改了文件路径,但 bash 缓存了"刚才执行过的命令在哪儿"。`hash -r` 清掉命令路径缓存,之后 `webhook` 才会重新查 PATH 找到新位置。

> 📌 你的情况:已经直接放到了 `/usr/bin/webhook`,**这个 Phase 没踩这个坑**,留着这个 Q6 是给别人看的。

### Q7:deploy.sh 跑 `docker compose` 报 exit status 125,body 显示 docker 帮助文本

`adnanh/webhook` 进程收到 POST → trigger rules 通过 → 调 `deploy.sh` → 脚本里 `docker compose -f docker-compose.prod.yml down` 这一步就挂,返回 `exit status 125` + body 是 docker 的 `--help` 输出(`--tlskey` / `--cert` / `--tlsverify` 等 global flags 那一坨)。

**原因**:你这台机器**只装了 v1 独立版 `docker-compose`(连字符)**,**没装 v2 插件 `docker compose`(空格)**。当你写 `docker compose ...`(空格),docker 把 `compose` 当成不知名子命令,fallback 到打帮助文本,**退出码 125**。

**两种修法**:

**A. 补装 v2 插件**(推荐,跟 doc 一致):
```bash
sudo dnf install -y docker-compose-plugin
docker compose version
```
> 🎯 应输出 `Docker Compose version v2.x.x`。**改完不用重推**,GitHub 那边 Recent deliveries → Redeliver 就行。

**B. 把 deploy.sh 改成 v1 命令**(v1 已经停止维护,长痛):
```bash
sudo sed -i 's/^docker compose /docker-compose /g' /root/webhook-deploy/deploy.sh
grep -n "docker-compose" /root/webhook-deploy/deploy.sh
```
> 🎯 一行 sed 把所有 `docker compose`(行首)替换成 `docker-compose`(连字符)。grep 验证 6 个调用点都对齐了。

**怎么避免下次踩**:**Phase 1 装 docker 那一段已经显式加了 v1/v2 验证命令**(`which docker docker-compose` + 两行 `version`),按那三步验装就不会撞这个坑。

---

## 5. 卸载 / 清理

```bash
sudo systemctl disable --now webhook
sudo rm /etc/systemd/system/webhook.service
sudo systemctl daemon-reload
sudo rm -rf /root/webhook-deploy
```
> 🎯 停服务 → 删 unit → 重载 systemd → 删整个 deploy 根目录(里面 hooks.json / deploy.sh / log / lock 一起带走)。
> 别忘 GitHub 仓库 `Settings → Webhooks` 删那条,`Deploy keys` 也要删,不然密钥留着就是攻击面。

docker compose 起来的应用本身想清:
```bash
cd /www/wwwroot/lab_devices_reservation
docker compose -f docker-compose.prod.yml down -v
```

---

## 附:本项目相关路径速查

| 用途 | 路径 |
|---|---|
| **部署根目录**(`chmod 700`,含 `deploy.sh` / `hooks.json` / `deploy.log` / `deploy.lock`) | **`/root/webhook-deploy/`** |
| 项目代码 | `/www/wwwroot/lab_devices_reservation` |
| 项目 .env | `/www/wwwroot/lab_devices_reservation/.env` |
| 生产 compose | `/www/wwwroot/lab_devices_reservation/docker-compose.prod.yml` |
| dev compose(**不要碰**) | `/www/wwwroot/lab_devices_reservation/docker-compose.yml` |
| 后端 Dockerfile | `/www/wwwroot/lab_devices_reservation/Dockerfile` |
| 前端 Dockerfile + nginx.conf | `/www/wwwroot/lab_devices_reservation/frontend/` |
| webhook systemd unit | `/etc/systemd/system/webhook.service` |
| webhook 二进制 | `/usr/bin/webhook` |
| compose 项目名 | `labprod`(`docker-compose.prod.yml` 顶级 `name`) |
| 容器名前缀 | `labprod-*`(`labprod-mysql-prod-1` / `labprod-app-1` / `labprod-frontend-1`) |
| webhook 监听端口 | `9000/tcp` |
| 前端暴露端口(公网) | `80/tcp` |
| 内部端口(app/mysql/redis) | **不暴露** |
| 后端健康检查(走前端) | `http://127.0.0.1/api/actuator/health`(`/api` 前缀别漏) |
| 后端健康检查(直连) | `http://app:8080/api/actuator/health`(仅 docker 网络内) |


### Chroma 1.0.0 向量库部署

AI 助手的 RAG 检索依赖 Chroma 容器。`docker-compose.yml` 已加入 `chroma` service：

```yaml
chroma:
  image: chromadb/chroma:1.0.0
  container_name: lab-chroma
  restart: unless-stopped
  volumes:
    - chroma_data:/chroma/chroma
  ports:
    - "127.0.0.1:9000:8000"   # 容器内 Chroma 默认监听 8000;host 暴露为 9000 避开常用端口
  environment:
    - IS_PERSISTENT=TRUE
    - PERSIST_DIRECTORY=/chroma/chroma
    - ANONYMIZED_TELEMETRY=FALSE
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9000/api/v2/heartbeat"]
    interval: 30s
    timeout: 5s
    retries: 3
```

部署步骤：

```bash
docker compose up -d chroma        # 仅启 chroma（开发期）
sleep 5
curl -s http://localhost:9000/api/v2/heartbeat   # 期望 {"nanosecond heartbeat": N}
```

数据迁移注意：
- Chroma 数据持久化在 `chroma_data` 卷（`/var/lib/docker/volumes/chroma_chroma_data`）；备份/恢复直接挂卷即可。
- 切换 embedding 模型（BGE-M3 → 别的）需要重建 collection——通过 `RagIngestService.rebuildCollection()` 调 `vectorStore.deleteCollection("lab_manuals")`，再重新 ingest。
- 单实例假设：所有 `ai_*` 表 + Chroma + Redis 全在同一台机器；横向扩展场景需考虑 Chroma 的分布式部署或迁到 Pinecone/Weaviate 等托管服务（论文列为未来工作）。
- 启动顺序：MySQL → Redis → Chroma → app；Chroma 健康检查失败不会阻塞 app 启动（Spring AI 是 lazy 初始化），但首次 RAG 调用会 503。

