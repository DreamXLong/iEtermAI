# iEtermAI

`iEtermAI` 是一个独立的 `iEterm` 查询执行器原型，支持 Windows 和 Mac 自动化后端。

目标是把自然语言查询拆成两层：

- `OpenClaw` 负责理解意图、选择工具、组织多轮流程
- `iEtermAI` 负责管理登录态、执行固定查询动作、解析返回结果

## 边界

- 只面向查询场景
- 不实现出票、改签、退票
- 不处理生产凭证托管
- 不把模型做成自由桌面操控代理

## 目录

- `操作文档.md`
  - Mac 版 iEterm 从打开软件、选择线路、登录确认到查价的完整操作步骤
- `app/main.py`
  - 本地 FastAPI 入口
- `app/models.py`
  - 请求、响应、状态模型
- `app/session.py`
  - 登录状态机与会话快照
- `app/executor.py`
  - 业务编排层，连接自动化驱动与解析器
- `app/automation_windows.py`
  - `mock` / `windows` / `macos` 三种自动化后端
- `app/parser.py`
  - 黑屏返回文本解析样例
- `requirements.txt`
  - 原型依赖

## 推荐调用链

1. 用户说“查明天北京到上海航班”
2. `OpenClaw` 把自然语言转成结构化参数
3. `OpenClaw` 调用 `ieterm.query_flight`
4. 本地执行器先确认 `iEterm` 窗口和登录状态
5. 已登录则发送查询指令，未登录则按状态机触发登录
6. 读取黑屏返回文本并解析成结构化结果
7. 把结果返回给 `OpenClaw`

## API

### `GET /health`

基础健康检查。

### `GET /session/status`

返回当前会话快照。

### `POST /session/ensure-ready`

确保 `iEterm` 已启动并进入可查询状态。

### `POST /session/login`

在执行器允许自动登录时触发登录流程。

Mac 版登录成功后如果出现“系统提示”弹窗，自动化流程会继续点击 `确定`，点掉后才进入可查询状态。

### `GET /session/login-aliases`

读取登录弹窗里“别名/线路”的下拉选项。

返回体示例：

```json
{
  "aliases": ["can826-01", "BJS177", "can826-05", "can826-06", "584-02", "其他"],
  "selected_alias": "can826-01"
}
```

### `POST /session/login-alias`

选择登录弹窗里的某一条“别名/线路”。

请求体示例：

```json
{
  "alias": "BJS177"
}
```

返回体示例：

```json
{
  "aliases": ["can826-01", "BJS177", "can826-05", "can826-06", "584-02", "其他"],
  "selected_alias": "BJS177"
}
```

### `POST /query/flight`

执行航班可用性查询。

请求体示例：

```json
{
  "origin": "BJS",
  "destination": "SHA",
  "departure_date": "2026-04-21",
  "prefer_direct_only": false
}
```

返回体示例：

```json
{
  "ok": true,
  "session_state": "logged_in",
  "issued_command": "AV BJS SHA 21APR",
  "flights": [
    {
      "flight_no": "MU5101",
      "depart_time": "08:00",
      "arrive_time": "10:15",
      "cabin": "Y",
      "availability": "9"
    }
  ],
  "raw_text": "..."
}
```

`issued_command` 只是模板示例。真实环境里应替换成你的 `iEterm` 指令格式。

### `POST /query/international-fare`

执行国际机票价格查询。第一版只查价，不订座、不出票。

请求体示例：

```json
{
  "origin": "BJS",
  "destination": "TYO",
  "departure_date": "2026-06-01",
  "airline": "CA",
  "passenger_type": "ADT"
}
```

返回体示例：

```json
{
  "ok": true,
  "session_state": "logged_in",
  "issued_command": "XS FSD BJSTYO/CA",
  "fares": [
    {
      "airline": "CA",
      "fare_basis": "YRTCN",
      "cabin": "Y",
      "currency": "CNY",
      "amount": "3200",
      "rule": "001",
      "passenger_type": "ADT",
      "raw_line": "CA YRTCN Y CNY 3200 RULE 001 ADT"
    }
  ],
  "raw_text": "..."
}
```

默认国际票价指令模板是：

```bash
IETERM_INTERNATIONAL_FARE_COMMAND_TEMPLATE=XS FSD {origin}{destination}{airline_part}
```

可用占位符：

- `{origin}`：出发城市或机场三字码，例如 `BJS`
- `{destination}`：到达城市或机场三字码，例如 `TYO`
- `{route}`：拼接后的航线，例如 `BJSTYO`
- `{departure_date}`：日期，例如 `01JUN`
- `{airline}`：航司代码，例如 `CA`
- `{airline_part}`：有航司时自动变成 `/CA`，没有航司时为空
- `{passenger_type}`：乘客类型，例如 `ADT`

不同 iEterm 环境的国际票价指令可能不同。如果你的系统不是 `XS FSD`，只需要在 `.env` 里替换这个模板。

## 运行

先复制一份配置：

```bash
cp .env.example .env
```

开发环境可以直接先用 `mock` 模式跑通 API：

```bash
IETERM_AUTOMATION_BACKEND=mock uvicorn app.main:app --reload
```

接真实 Windows `iEterm` 时再切到 `windows`：

```bash
IETERM_AUTOMATION_BACKEND=windows uvicorn app.main:app --reload
```

接真实 Mac 版 `iEterm` 时切到 `macos`：

```bash
IETERM_AUTOMATION_BACKEND=macos uvicorn app.main:app --reload
```

完整启动步骤：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 现在能不能直接用

可以分三层理解：

- 现在已经可以直接启动服务，并用 `mock` 模式跑通完整查询链路
- 如果要真的操作 Windows 版 `iEterm`，还需要你补真实环境配置，例如窗口标题、登录控件、查询指令模板
- 如果要真的操作 Mac 版 `iEterm`，需要开启 macOS 辅助功能权限，并确认应用名、进程名、查询指令模板

`windows` 模式已经不是纯占位了，已经具备这些能力：

- 按窗口标题或正则定位主窗口
- 按需启动 `iEterm`
- 识别登录态 / 会话过期态
- 用键盘向黑屏窗口发送命令
- 优先用剪贴板读取文本，失败后回退到 UI 树文本
- 在配置了登录控件后执行自动登录

`macos` 模式也已具备基础能力：

- 按应用名启动或激活 `iEterm Mac版`
- 读取登录弹窗里的线路/别名下拉列表
- 按名称选择指定线路/别名
- 在登录信息已填好的情况下点击 `登 录` 按钮
- 通过剪贴板粘贴查询指令并按回车
- 通过全选复制读取黑屏窗口文本
- 根据返回文本中的关键字识别登录页和会话过期

第一次使用 Mac 自动化时，需要在系统设置里给运行 Python/终端的程序开启权限：

1. 打开 `系统设置`
2. 进入 `隐私与安全性`
3. 打开 `辅助功能`
4. 允许 `Terminal`、`iTerm`、`Cursor` 或实际运行服务的程序控制电脑

如果应用名不是 `iEterm Mac版`，需要在 `.env` 里修改：

```bash
IETERM_MAC_APP_NAME=iEterm Mac版
IETERM_MAC_PROCESS_NAME=
```

如果活动监视器里看到的进程名和 Dock 上的应用名不同，就把真实进程名填到 `IETERM_MAC_PROCESS_NAME`。

登录线路选择流程：

1. 打开 `iEterm Mac版`，停留在登录弹窗
2. 启动服务：

```bash
IETERM_AUTOMATION_BACKEND=macos uvicorn app.main:app --reload
```

3. 获取可选线路：

```bash
curl http://127.0.0.1:8000/session/login-aliases
```

4. 选择其中一条线路：

```bash
curl -X POST http://127.0.0.1:8000/session/login-alias \
  -H "Content-Type: application/json" \
  -d '{"alias": "BJS177"}'
```

5. 点击登录按钮：

```bash
curl -X POST http://127.0.0.1:8000/session/login
```

这个接口只点击 `登 录` 按钮，不读取、不保存你的密码。登录成功后如果出现“系统提示”弹窗，会继续点击 `确定`。第一次建议先人工确认用户名、密码、认证方式、服务器和端口都正确。

更完整的操作步骤见 `操作文档.md`。

但它仍然依赖你的真实客户端细节，所以第一次接入时通常还要调这几项：

- `IETERM_EXECUTABLE_PATH`
- `IETERM_WINDOW_TITLE` 或 `IETERM_WINDOW_TITLE_RE`
- `IETERM_MAC_APP_NAME`
- `IETERM_MAC_PROCESS_NAME`
- `IETERM_USERNAME_CONTROL`
- `IETERM_PASSWORD_CONTROL`
- `IETERM_SUBMIT_CONTROL`
- `IETERM_AVAILABILITY_COMMAND_TEMPLATE`

## OpenClaw 接入建议

不要让 `OpenClaw` 直接控制桌面。

建议只暴露这类高层工具：

- `ieterm.session_status`
- `ieterm.ensure_ready`
- `ieterm.login`
- `ieterm.query_flight`
- `ieterm.query_international_fare`

工具调用契约示例：

```json
{
  "tool": "ieterm.query_flight",
  "arguments": {
    "origin": "BJS",
    "destination": "SHA",
    "departure_date": "2026-04-21"
  }
}
```

国际票价查询工具调用契约示例：

```json
{
  "tool": "ieterm.query_international_fare",
  "arguments": {
    "origin": "BJS",
    "destination": "TYO",
    "departure_date": "2026-06-01",
    "airline": "CA",
    "passenger_type": "ADT"
  }
}
```

## 凭证与登录

- 用户名密码应存放在 Windows Credential Manager 或其他本机安全存储
- 如果登录需要验证码、短信或 UKey，应改为人工登录后维持会话
- 模型不应直接持有明文凭证

## 后续接真实环境时要补的内容

- 根据你的 `iEterm` 黑屏格式调整命令模板和解析规则
- 把 `.env` 中的登录控件名改成真实选择器
- 增加超时、弹窗、焦点丢失、会话过期的恢复逻辑
- 为高风险动作增加白名单和审计
