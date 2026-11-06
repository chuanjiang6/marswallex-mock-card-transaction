---
name: marswallex-mock-card-transaction
description: 在 MarsWallex 测试环境模拟卡交易（授权、授权失败、授权撤销、结算、退款、跨币种、跨境），自动完成 OpenAPI 签名并汇总结果。用户提到模拟交易、模拟消费、模拟授权、模拟结算、模拟退款、测试卡交易 Webhook、联调交易回调、mock transaction 时使用。只能访问测试环境。
---

# MarsWallex 模拟卡交易

在 MarsWallex 测试环境调用 `POST /v1/card/mock-transactions`，模拟卡组织发来的授权、撤销、结算、退款。
模拟交易与真实交易走同一套记账和通知流程：会变动测试环境的卡余额、收取手续费，并推送交易 Webhook。

以下路径都相对本 skill 目录（`SKILL.md` 所在目录）。

- 脚本：`scripts/mock_txn.py`
- 配置：`config/config.env`（模板 `config/config.env.example`）
- 接口说明：`references/api.md`
- 常见用例：`references/scenarios.md`
- 不用脚本时的签名方法（Apifox 前置脚本、curl）：`references/manual-signing.md`

## 安全约束

- 只访问测试环境。脚本只放行 `feibeiglobal-test.com` 域名，不要修改这个限制去访问生产环境。
- 不读取、不输出 `config/config.env` 中的 `API_TOKEN` 和私钥。脚本输出的认证头已脱敏。
- 每次发送前先向用户列出将要执行的请求（卡、金额、交易类型），用户确认后再执行。用户已明确说「直接执行」时可以不等确认，但仍要先列出。
- 金额尽量小（如 0.10–10.00），避免影响测试卡的后续使用。

## 准备

1. Python 3.8 及以上，安装依赖：`pip install cryptography`。
2. 复制 `config/config.env.example` 为 `config/config.env`，填写 `DEVELOPER_ID`、`API_TOKEN` 和私钥。配置项未填写时脚本退出码为 2，提示缺哪一项；此时请用户填写，不要编造。
3. 本机出口 IP 需要在开放平台的 IP 白名单中，否则返回 401 `The ip is not authorized`。
4. 准备一张测试环境的卡，记下卡 ID（`card_id`）和卡币种。

## 命令

```bash
cd <skill 目录>/scripts

# 授权（消费）成功 / 失败
python3 mock_txn.py auth --card-id <卡ID> --amount 10.00
python3 mock_txn.py auth --card-id <卡ID> --amount 10.00 --fail --decline-reason "Insufficient funds"

# 指定商家（跨境：country 与卡产品地区不同）
python3 mock_txn.py auth --card-id <卡ID> --amount 10.00 --merchant-name "US STORE" --mcc 5311 --country US

# 跨币种：账单金额为卡币种，交易金额为商户币种
python3 mock_txn.py auth --card-id <卡ID> --amount 10.00 --txn-amount 78.00 --txn-currency HKD

# 授权撤销
python3 mock_txn.py reversal --origin <授权单号>

# 结算：有原授权（不传 --amount 默认全额）/ 部分结算 / 无授权直接结算
python3 mock_txn.py settle --card-id <卡ID> --origin <授权单号>
python3 mock_txn.py settle --card-id <卡ID> --origin <授权单号> --amount 4.00
python3 mock_txn.py settle --card-id <卡ID> --amount 5.00

# 退款：有原授权 / 无原交易
python3 mock_txn.py refund --card-id <卡ID> --origin <授权单号> --amount 3.00
python3 mock_txn.py refund --card-id <卡ID> --amount 2.00

# 按交易单号查询（authorization：授权与撤销；settlement：结算与退款）
python3 mock_txn.py query --kind authorization --transaction-id <单号>
python3 mock_txn.py query --kind settlement --transaction-id <单号>

# 自定义请求体
python3 mock_txn.py raw --json '{"transaction_type":"AUTH","card_id":123,"billing_amount":"1.00"}'

# 只看签名原文和请求，不发送（排查验签失败）
python3 mock_txn.py --dry-run auth --card-id <卡ID> --amount 1.00
```

所有子命令的 `--origin` 都是**原授权单号**（授权接口返回的 `transaction_id`），不是结算单号。

## 输出与退出码

输出为 JSON：

- `request`：请求地址、请求体、签名原文 `sign_text`、脱敏后的认证头。
- `response`：`http_status`、`trace_id`（响应头 `X-Trace-Id`，联系 MarsWallex 排查时提供）、`body`。
- `summary`：提炼后的结果，`success` 为 true 表示 HTTP 2xx，此外包含 `transaction_id`、`transaction_type`、`status`、金额币种、手续费；失败时为 `code` 和 `message`。

退出码：`0` 已拿到响应（不代表业务成功，看 `summary.success` 与 `status`）；`2` 配置或参数错误；`4` 网络错误。

**注意**：`summary.success = true` 只代表请求被受理。授权失败的模拟（`--fail`）也返回 HTTP 200，`status` 为 `failed`。

## 执行流程

1. **确认需求**：用户要模拟什么场景、用哪张卡。没说场景时，到 `references/scenarios.md` 选最接近的用例。
2. **列出请求清单**，等用户确认：

   ```markdown
   **卡**：<卡ID>（<币种>）

   | 步骤 | 交易类型 | 关键参数 | 预期 status | 预期 Webhook |
   | ---- | -------- | -------- | ----------- | ------------ |
   | 1 | AUTH | amount=10.00 | approved | AUTH_EVENT |
   | 2 | SETTLE | origin=步骤1，全额 | approved | SETTLE_EVENT |
   ```

3. **按顺序执行**。后一步用到前一步的单号时，从上一步输出的 `summary.transaction_id` 取。某一步失败时停下，先根据 `summary.message` 和下方「常见报错」判断原因，再决定是否继续。
4. **需要核对时**用 `query` 命令按单号查询，或请用户查看自己的 Webhook 接收日志。
5. **表格汇总**：

   ```markdown
   **结论**：<共 N 步，成功 X 步>

   | 步骤 | 交易类型 | 交易单号 | 原授权单号 | status | 账单金额 | 交易金额 | 手续费 | 结果 |
   | ---- | -------- | -------- | ---------- | ------ | -------- | -------- | ------ | ---- |
   ```

   结果列用 ✅（与预期一致）或 ❌（与预期不一致）；❌ 的步骤在表格下写明返回的 `code`、`message` 和 `trace_id`。

## 常见报错

| 返回 | 原因 | 处理 |
| ---- | ---- | ---- |
| 401 `Unauthorized` | `DEVELOPER_ID` / `API_TOKEN` 错误，或私钥与登记的公钥不匹配 | 核对配置；用 `--dry-run` 查看签名原文 |
| 401 `The ip is not authorized` | 本机出口 IP 不在白名单 | 在开放平台添加 IP 白名单 |
| 400 `The timestamp is invalid` | 本机时间与标准时间相差超过 300 秒 | 校准本机时间 |
| 404（无 JSON 或 `RESOURCE_NOT_FOUND` 且无其他信息） | 当前环境未开放模拟交易 | 联系 MarsWallex 确认 |
| 404 `Card not found` / `This card not exist` | 卡 ID 不存在，或不属于当前商户 | 核对卡 ID |
| 404 `Transaction not found` | 原授权单号错误、不属于当前商户，或传成了结算单号 | `--origin` 传授权单号 |
| 400 `origin_transaction_id does not belong to card_id` | 原授权不是这张卡的 | 核对卡 ID 与原授权单号 |
| 400 `Authorization is not approved` | 原授权是失败的授权 | 换一笔成功的授权 |
| 400 `Authorization has been reversed` | 原授权已撤销，不能再结算或撤销 | 换一笔授权 |
| 400 `Authorization has been settled` | 已结算的授权不能撤销 | 改用退款 |
| 400 `billing_amount is required when the authorization has been partially settled` | 授权已部分结算，再次结算需指定金额 | 传 `--amount` |
| 400 `Unsupported card` | 该卡开启了外汇加点，不支持跨币种模拟 | 改用同币种，或换一张卡 |
| 400 `billing_currency must be the card currency` | 账单币种与卡币种不同 | 不传 `--currency`，或传卡币种 |
| 400 `transaction_amount is required when transaction_currency differs from billing_currency` | 跨币种没传交易金额 | 补 `--txn-amount` |
| 400 `transaction_amount must equal billing_amount when the currencies are the same` | 同币种时两个金额不一致 | 去掉 `--txn-amount` |
| 400 `Unsupported transaction_currency` | 币种代码不支持 | 使用 ISO 4217 法币代码 |
| 500 | 平台处理异常，交易可能已部分处理 | 不要直接重试（接口没有幂等，重试会生成新交易），记录 `trace_id` 联系 MarsWallex |
