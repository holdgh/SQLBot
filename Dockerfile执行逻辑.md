# 第二个Dockerfile完整分析（业务应用镜像，基于刚才的sqlbot-base基础镜像）
整体架构：**多阶段构建（4个构建阶段 + 最终运行阶段）**
> 阶段清单：
> 1. `vector-model`：向量模型文件来源阶段，只拷贝模型权重，不编译
> 2. `sqlbot-ui-builder`：前端React/Vue构建阶段（`npm install + build`编译前端产物dist）
> 3. `sqlbot-builder`：后端Python业务代码构建，使用uv安装python依赖、创建虚拟环境
> 4. `ssr-builder`：G2图表SSR服务构建阶段（Node渲染图表服务）
> 5. 最终runtime阶段：`sqlbot-python-pg:latest`，组装前面所有阶段产出，作为容器运行镜像

> 依赖关系：
> `sqlbot-ui-builder` / `sqlbot-builder` / `ssr-builder` **全部FROM你上一个sqlbot-base基础镜像**
> 最后运行镜像`sqlbot-python-pg`，推测是sqlbot-base的精简运行版本（保留运行时，去掉编译工具）

## 逐阶段拆解
### 阶段1：vector-model
```dockerfile
FROM ghcr.io/1panel-dev/maxkb-vector-model:v1.0.1 AS vector-model
```
仅作为文件载体，**不执行任何构建**。后面最终阶段会从这个镜像拷贝向量模型目录`/opt/maxkb/app/model`到sqlbot的models目录，用于向量检索、语义解析。

### 阶段2：sqlbot-ui-builder（前端打包阶段）
```dockerfile
FROM --platform=${BUILDPLATFORM} registry.cn-qingdao.aliyuncs.com/dataease/sqlbot-base:latest AS sqlbot-ui-builder
ENV SQLBOT_HOME=/opt/sqlbot
ENV APP_HOME=${SQLBOT_HOME}/app
ENV UI_HOME=${SQLBOT_HOME}/frontend
ENV DEBIAN_FRONTEND=noninteractive

RUN mkdir -p ${APP_HOME} ${UI_HOME}

COPY frontend /tmp/frontend
RUN cd /tmp/frontend && npm install && npm run build && mv dist ${UI_HOME}/dist
```
1. 基于`sqlbot-base`（上一个基础镜像，自带Node18）
2. 把本地`frontend`前端源码复制进容器，执行`npm install`安装前端依赖，`npm run build`打包生成静态dist产物
3. 将打包后的dist静态文件放到`${UI_HOME}/dist`
> 这个阶段**只产出前端静态资源**，不会带进node_modules源码；后面runtime镜像只拷贝dist打包产物。

### 阶段3：sqlbot-builder（Python后端构建阶段）
```dockerfile
FROM registry.cn-qingdao.aliyuncs.com/dataease/sqlbot-base:latest AS sqlbot-builder
# 环境变量
ENV PYTHONUNBUFFERED=1
ENV SQLBOT_HOME=/opt/sqlbot
ENV APP_HOME=${SQLBOT_HOME}/app
ENV UI_HOME=${SQLBOT_HOME}/frontend
ENV PYTHONPATH=${SQLBOT_HOME}/app
ENV PATH="${APP_HOME}/.venv/bin:$PATH"
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV DEBIAN_FRONTEND=noninteractive

RUN mkdir -p ${APP_HOME} ${UI_HOME}
WORKDIR ${APP_HOME}

# 从ui构建阶段拷贝前端dist产物
COPY  --from=sqlbot-ui-builder ${UI_HOME} ${UI_HOME}

# uv缓存挂载，优先用uv.lock锁定依赖
RUN test -f "./uv.lock" && \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project || echo "uv.lock file not found, skipping intermediate-layers"

COPY ./backend ${APP_HOME}

# 最终完整安装全部Python依赖，创建.venv虚拟环境
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra cpu
```
1. 同样基于`sqlbot-base`，自带python3.11、uv、gcc编译链，可以编译python原生扩展包
2. 先把上一阶段打包好的前端dist拷贝进来
3. 使用`uv`做python依赖管理，带buildkit缓存挂载`--mount=cache`，提升本地构建速度
4. 先尝试锁定文件安装；再拷贝后端业务源码，执行`uv sync --extra cpu`，构建独立`.venv`虚拟环境，把项目全部依赖安装到虚拟环境
> 关键点：所有python依赖安装**在builder阶段完成**，最终镜像直接拷贝`.venv`虚拟环境，runtime镜像不需要再编译安装包。

### 阶段4：ssr-builder（G2图表SSR渲染服务）
```dockerfile
FROM registry.cn-qingdao.aliyuncs.com/dataease/sqlbot-base:latest AS ssr-builder
WORKDIR /app

# 安装系统图形渲染依赖（cairo/pango等，就是基础镜像预装的那一堆图形库，这里额外补齐）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3 pkg-config \
    libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    libpixman-1-dev libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

# 关闭npm审计、fund提示，减少构建干扰
RUN npm config set fund false \
    && npm config set audit false \
    && npm config set progress false

COPY g2-ssr/app.js g2-ssr/package.json /app/
COPY g2-ssr/charts/* /app/charts/
RUN npm install
```
G2是AntV图表库；这个阶段构建**Node端SSR图表渲染服务**。
- 用于后端生成图片形式的图表（问数场景，把SQL查询结果渲染成图片返回给前端）
- cairo/pango是无头环境下渲染svg/图片必备图形库
- 拷贝g2-ssr代码，执行npm install安装node依赖，产出node_modules。后续runtime直接拷贝/app目录。

### 最终 Runtime 阶段（容器运行镜像，重点）
```dockerfile
FROM registry.cn-qingdao.aliyuncs.com/dataease/sqlbot-python-pg:latest
# 设置时区上海
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone

# runtime环境变量
ENV PYTHONUNBUFFERED=1
ENV SQLBOT_HOME=/opt/sqlbot
ENV PYTHONPATH=${SQLBOT_HOME}/app
ENV PATH="${SQLBOT_HOME}/app/.venv/bin:$PATH"

# 内置Postgres默认账号密码（容器自带pg库）
ENV POSTGRES_DB=sqlbot
ENV POSTGRES_USER=root
ENV POSTGRES_PASSWORD=Password123@pg

# 从各个构建阶段拷贝产物（核心！）
COPY start.sh /opt/sqlbot/app/start.sh
COPY g2-ssr/*.ttf /usr/share/fonts/truetype/liberation/
COPY --from=sqlbot-builder ${SQLBOT_HOME} ${SQLBOT_HOME}
COPY --from=ssr-builder /app /opt/sqlbot/g2-ssr
COPY --from=vector-model /opt/maxkb/app/model /opt/sqlbot/models

WORKDIR ${SQLBOT_HOME}/app

RUN mkdir -p /opt/sqlbot/images /opt/sqlbot/g2-ssr

# 开放端口
EXPOSE 3000 8000 8001 5432
# 健康检查：访问8000后端服务端口
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import os, urllib.request; urllib.request.urlopen(f'[http://localhost:8000/](http://localhost:8000/){os.environ.get(\"CONTEXT_PATH\", \"\")}', timeout=3)" || exit 1

ENTRYPOINT ["sh", "start.sh"]
```
1. 基础镜像换成`sqlbot-python-pg:latest`，**不是sqlbot-base**，这是精简后的运行底座：保留python运行时、postgres、各类数据库客户端；**移除gcc、build-essential等编译工具**，缩小最终镜像体积。
2. 依次拷贝：
    - 启动脚本start.sh（容器入口）
    - 图表字体文件
    - sqlbot-builder阶段：后端代码 + .venv虚拟环境 + 前端dist静态文件
    - ssr-builder阶段：g2图表渲染服务完整代码+node_modules
    - vector-model阶段：向量模型文件
3. 暴露端口说明：
    - 8000：python后端API主服务（健康检查监听此端口）
    - 3000/8001：前端静态服务 / g2 ssr图表服务
    - 5432：容器内置PostgreSQL数据库端口
4. 健康检查：每30s访问8000端口，验证后端服务存活
5. 入口：`sh start.sh`，由这个脚本统一拉起：Postgres、python后端、G2 SSR多个进程（**单容器多进程**）

# 两个Dockerfile整体关系对比
|文件|角色|特点|
| ---- | ---- | ---- |
|第一个Dockerfile|`sqlbot-base` 基础构建镜像|重型底座，预装编译工具、Python、Node、Oracle/达梦客户端、postgres。**用于编译阶段（builder），不作为最终运行镜像**|
|第二个Dockerfile|SQLBot业务应用镜像|多阶段构建，利用sqlbot-base编译前端、python后端、图表服务；最终runtime用精简`sqlbot-python-pg`，把所有编译产物打包，直接启动整套问数应用。|

# 关键亮点 & 潜在问题
## ✅亮点
1. 严格分离**构建阶段和运行阶段**：编译工具只存在builder阶段，最终runtime镜像剔除gcc等编译依赖，减小镜像大小；
2. 分层编译：前端、python后端、图表SSR、向量模型拆成独立阶段，修改其中一部分，不会全量重构建；
3. uv+buildkit缓存，加速python依赖安装；虚拟环境整体拷贝到运行镜像，环境一致性好；
4. 内置G2图表SSR，适配ChatBI问数出图场景；内置向量模型，用于语义解析；
5. 健康检查、时区、默认数据库环境变量都预先配置。

## ⚠️潜在风险/设计缺陷
1. **单容器多进程**：start.sh里面同时启动Postgres数据库、Python后端、Node SSR服务。容器设计最佳实践是一个容器一个进程；多进程一旦某个子进程崩溃，容器不会自动退出，健康检查仅监控8000后端，postgres/ssr挂掉不会被捕获。
2. 最终镜像内置PostgreSQL，数据库数据存在容器内部；容器销毁数据丢失，生产环境建议外部独立PG。
3. 前端打包放在builder阶段，每次构建镜像都会完整执行npm install，构建耗时长；
4. 多阶段镜像链很长，镜像层级多，调试困难；
5. 默认数据库密码硬编码写在Dockerfile环境变量，生产必须覆盖。
6. 所有阶段都复用sqlbot-base，镜像体积本身很大。

# 一句话总结整套构建链路
先用第一个Dockerfile构建**sqlbot-base（编译用重型基础镜像）**，再用第二个Dockerfile做多阶段构建：
> 在sqlbot-base上编译前端静态资源、安装Python虚拟环境、构建G2图表渲染服务；然后把所有产物复制到精简运行镜像sqlbot-python-pg，打包成完整SQLBot应用镜像，容器启动后同时拉起Postgres、后端API、图表SSR服务，提供ChatBI问数能力。

如果你想，我可以帮你梳理start.sh大概率会做哪些操作，或者画一份构建流程图。